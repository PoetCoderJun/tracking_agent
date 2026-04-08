from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from websockets.exceptions import ConnectionClosed
from websockets.legacy.server import WebSocketServerProtocol, serve

from backend.project_paths import resolve_project_path
from backend.skills import build_viewer_modules
from backend.perception.service import LocalPerceptionService
from backend.persistence import ActiveSessionStore, LiveSessionStore, resolve_session_id
from backend.session_frames import tracking_recent_frames


def _enriched_conversation_history(
    *,
    session_payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    raw_history = list(session_payload.get("conversation_history") or [])
    result_history = list(session_payload.get("result_history") or [])
    debug_by_timestamp: Dict[str, Dict[str, Any]] = {}
    for item in result_history:
        if not isinstance(item, dict):
            continue
        timestamp = str(item.get("updated_at", "")).strip()
        if not timestamp:
            continue
        debug_by_timestamp[timestamp] = dict(item)

    enriched: List[Dict[str, Any]] = []
    for entry in raw_history:
        if not isinstance(entry, dict):
            continue
        normalized = {
            "role": str(entry.get("role", "")).strip(),
            "text": str(entry.get("text", "")).strip(),
            "timestamp": str(entry.get("timestamp", "")).strip(),
        }
        if normalized["role"] == "assistant":
            debug_payload = debug_by_timestamp.get(normalized["timestamp"])
            if debug_payload is not None:
                normalized["debug"] = debug_payload
        enriched.append(normalized)
    return enriched


def build_agent_viewer_payload(*, state_root: Path, session_id: str | None = None) -> Dict[str, Any]:
    store = LiveSessionStore(state_root=state_root)
    resolved_session_id = resolve_session_id(state_root=state_root, session_id=session_id)
    if resolved_session_id is None:
        return {
            "kind": "agent_viewer_state",
            "session_id": None,
            "available": False,
            "message": "No active session yet.",
        }

    session_path = store.session_path(resolved_session_id)

    if not session_path.exists():
        return {
            "kind": "agent_viewer_state",
            "session_id": resolved_session_id,
            "available": False,
            "message": "Session not found yet.",
        }

    session = store.session_payload(resolved_session_id)
    perception = LocalPerceptionService(state_root)
    perception_snapshot = perception.read_snapshot()
    stream_status = dict(perception_snapshot.get("stream_status") or {})
    recent_frames = tracking_recent_frames(
        state_root=state_root,
        session_id=resolved_session_id,
        raw_session=session,
    )
    latest_result = dict(session.get("latest_result") or {})
    modules = build_viewer_modules(
        session=session,
        state_root=state_root,
        perception_snapshot=perception_snapshot,
        recent_frames=recent_frames,
    )
    primary_module_name = next(iter(modules.keys()), None)
    primary_module = {} if primary_module_name is None else dict(modules[primary_module_name] or {})
    latest_frame = primary_module.get("display_frame")
    if latest_frame is None and recent_frames:
        latest_frame = dict(recent_frames[-1])

    return {
        "kind": "agent_viewer_state",
        "available": True,
        "session_id": resolved_session_id,
        "updated_at": session.get("updated_at"),
        "agent": {
            "latest_result": latest_result or None,
            "conversation_history": _enriched_conversation_history(session_payload=session),
            "turn_history": list(session.get("result_history") or []),
        },
        "observation": {
            "latest_frame": latest_frame,
            "stream_status": stream_status.get("status"),
            "detection_count": 0
            if latest_frame is None
            else len(latest_frame.get("detections") or []),
        },
        "modules": modules,
        "summary": {
            "primary_module": primary_module_name,
            "target_id": primary_module.get("target_id"),
            "pending_question": primary_module.get("pending_question"),
            "status_kind": primary_module.get("status_kind"),
            "status_label": primary_module.get("status_label"),
            "stream_status": stream_status.get("status"),
            "detection_count": 0 if latest_frame is None else len(latest_frame.get("detections") or []),
            "frame_id": None if latest_frame is None else latest_frame.get("frame_id"),
        },
    }


def _file_signature(*, state_root: Path, session_id: str | None = None) -> Tuple[int, int, int]:
    active_session_path = ActiveSessionStore(state_root).path()
    active_session_mtime = active_session_path.stat().st_mtime_ns if active_session_path.exists() else -1
    resolved_session_id = resolve_session_id(state_root=state_root, session_id=session_id)
    if resolved_session_id is None:
        return (active_session_mtime, -1, -1)

    session_path = LiveSessionStore(state_root=state_root).session_path(resolved_session_id)
    perception_path = state_root / "perception" / "snapshot.json"
    session_mtime = session_path.stat().st_mtime_ns if session_path.exists() else -1
    perception_mtime = perception_path.stat().st_mtime_ns if perception_path.exists() else -1
    return (active_session_mtime, session_mtime, perception_mtime)


class AgentViewerStreamServer:
    def __init__(
        self,
        *,
        state_root: Path,
        session_id: str | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
        poll_interval: float = 1.0,
    ):
        self._state_root = state_root
        self._session_id = session_id
        self._host = host
        self._port = port
        self._poll_interval = poll_interval

    async def _handler(self, websocket: WebSocketServerProtocol) -> None:
        last_signature: Optional[Tuple[int, int, int]] = None
        while True:
            try:
                signature = _file_signature(state_root=self._state_root, session_id=self._session_id)
                if signature != last_signature:
                    payload = build_agent_viewer_payload(
                        state_root=self._state_root,
                        session_id=self._session_id,
                    )
                    await websocket.send(json.dumps(payload, ensure_ascii=False))
                    last_signature = signature
                await asyncio.sleep(self._poll_interval)
            except ConnectionClosed:
                return

    async def serve_forever(self) -> None:
        async with serve(self._handler, self._host, self._port):
            await asyncio.Future()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the tracking viewer websocket stream for one session or the active session."
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, follows the current active session.",
    )
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = AgentViewerStreamServer(
        state_root=resolve_project_path(args.state_root),
        session_id=args.session_id,
        host=args.host,
        port=args.port,
        poll_interval=args.poll_interval,
    )
    asyncio.run(server.serve_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
