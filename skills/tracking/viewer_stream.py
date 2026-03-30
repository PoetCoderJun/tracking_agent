from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from websockets.exceptions import ConnectionClosed
from websockets.legacy.server import WebSocketServerProtocol, serve

from backend.agent.memory import AgentMemoryStore
from backend.persistence import ActiveSessionStore, LiveSessionStore, resolve_session_id
from backend.project_paths import resolve_project_path


def _normalize_tracking_state(memory_payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = dict(((memory_payload.get("skill_cache") or {}).get("tracking") or {}))
    return {
        **raw,
        "latest_target_id": raw.get("latest_target_id", raw.get("target_id")),
        "latest_memory": str(raw.get("latest_memory", raw.get("memory", "")) or "").strip(),
        "pending_question": str(
            raw.get("pending_question", raw.get("clarification_question", "")) or ""
        ).strip(),
    }


def _image_data_url(path_value: Any) -> Optional[str]:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    path = resolve_project_path(raw)
    if not path.exists() or not path.is_file():
        return None
    mime_type, _ = mimetypes.guess_type(path.name)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type or 'image/jpeg'};base64,{encoded}"


def _memory_history(result_history: List[Dict[str, Any]], limit: int = 6) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    last_memory = None
    for entry in reversed(list(result_history)):
        memory = str(entry.get("memory", "") or "").strip()
        if not memory:
            continue
        if memory == last_memory:
            continue
        collected.append(
            {
                "updated_at": entry.get("updated_at"),
                "frame_id": entry.get("frame_id"),
                "target_id": entry.get("target_id", entry.get("track_id")),
                "behavior": entry.get("behavior"),
                "memory": memory,
            }
        )
        last_memory = memory
        if len(collected) >= limit:
            break
    return list(reversed(collected))


def _target_bbox(
    *,
    latest_result: Dict[str, Any],
    tracking_state: Dict[str, Any],
    display_frame: Dict[str, Any],
) -> Optional[List[int]]:
    bbox = latest_result.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        return [int(value) for value in bbox]

    target_id = latest_result.get("target_id", tracking_state.get("latest_target_id"))
    if target_id in (None, ""):
        return None

    for detection in display_frame.get("detections") or []:
        detection_target_id = detection.get("track_id", detection.get("target_id"))
        detection_bbox = detection.get("bbox")
        if detection_target_id is None or not isinstance(detection_bbox, list) or len(detection_bbox) != 4:
            continue
        if str(detection_target_id) != str(target_id):
            continue
        return [int(value) for value in detection_bbox]
    return None


def build_tracking_viewer_payload(*, state_root: Path, session_id: str | None = None) -> Dict[str, Any]:
    store = LiveSessionStore(state_root=state_root)
    resolved_session_id = resolve_session_id(state_root=state_root, session_id=session_id)
    if resolved_session_id is None:
        return {
            "kind": "tracking_viewer_state",
            "session_id": None,
            "available": False,
            "message": "No active session yet.",
        }

    memory_store = AgentMemoryStore(state_root, resolved_session_id)
    session_path = store.session_path(resolved_session_id)

    if not session_path.exists():
        return {
            "kind": "tracking_viewer_state",
            "session_id": resolved_session_id,
            "available": False,
            "message": "Session not found yet.",
        }

    session = store.session_payload(resolved_session_id)
    memory_payload = (
        json.loads(memory_store.path().read_text(encoding="utf-8"))
        if memory_store.path().exists()
        else {"skill_cache": {}}
    )
    tracking_state = _normalize_tracking_state(memory_payload)
    recent_frames = list(session.get("recent_frames") or [])
    latest_result = dict(session.get("latest_result") or {})
    display_frame = None
    result_frame_id = str(latest_result.get("frame_id", "") or "").strip()
    if result_frame_id:
        for frame in recent_frames:
            if str(frame.get("frame_id", "")).strip() == result_frame_id:
                display_frame = dict(frame)
                break
    if display_frame is None and recent_frames:
        display_frame = dict(recent_frames[-1])

    display_frame_payload = None
    if display_frame is not None:
        display_frame_payload = {
            **display_frame,
            "target_id": latest_result.get("target_id", tracking_state.get("latest_target_id")),
            "bbox": _target_bbox(
                latest_result=latest_result,
                tracking_state=tracking_state,
                display_frame=display_frame,
            ),
            "image_data_url": _image_data_url(display_frame.get("image_path")),
        }

    return {
        "kind": "tracking_viewer_state",
        "available": True,
        "session_id": resolved_session_id,
        "updated_at": session.get("updated_at"),
        "latest_result": latest_result or None,
        "display_frame": display_frame_payload,
        "current_memory": tracking_state.get("latest_memory", ""),
        "memory_history": _memory_history(list(session.get("result_history") or [])),
        "conversation_history": list(session.get("conversation_history") or [])[-8:],
        "turn_history": list(session.get("result_history") or [])[-6:],
        "summary": {
            "target_id": tracking_state.get("latest_target_id"),
            "pending_question": tracking_state.get("pending_question"),
            "detection_count": 0
            if display_frame_payload is None
            else len(display_frame_payload.get("detections") or []),
            "frame_id": None if display_frame_payload is None else display_frame_payload.get("frame_id"),
        },
    }


def _file_signature(*, state_root: Path, session_id: str | None = None) -> Tuple[int, int, int]:
    active_session_path = ActiveSessionStore(state_root).path()
    active_session_mtime = active_session_path.stat().st_mtime_ns if active_session_path.exists() else -1
    resolved_session_id = resolve_session_id(state_root=state_root, session_id=session_id)
    if resolved_session_id is None:
        return (active_session_mtime, -1, -1)

    session_path = LiveSessionStore(state_root=state_root).session_path(resolved_session_id)
    memory_path = AgentMemoryStore(state_root, resolved_session_id).path()
    session_mtime = session_path.stat().st_mtime_ns if session_path.exists() else -1
    memory_mtime = memory_path.stat().st_mtime_ns if memory_path.exists() else -1
    return (active_session_mtime, session_mtime, memory_mtime)


class TrackingViewerStreamServer:
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
                    payload = build_tracking_viewer_payload(
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
