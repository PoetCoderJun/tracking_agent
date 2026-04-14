from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from agent.state.active import resolve_session_id
from agent.state.backend import BackendStore
from interfaces.viewer.skill_modules import build_viewer_modules
from world.perception import recent_frames
from world.perception.service import LocalPerceptionService


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


def _with_rendered_image_path(module_payload: Dict[str, Any]) -> Dict[str, Any]:
    display_frame = module_payload.get("display_frame")
    if not isinstance(display_frame, dict):
        return module_payload
    if not str(display_frame.get("image_path", "")).strip():
        return module_payload
    return {
        **module_payload,
        "display_frame": {
            **display_frame,
            "rendered_image_path": "/viewer-frame.jpg",
        },
    }


def build_agent_viewer_payload(*, state_root: Path, session_id: str | None = None) -> Dict[str, Any]:
    store = BackendStore(state_root=state_root)
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
    frames = recent_frames(state_root=state_root)
    latest_result = dict(session.get("latest_result") or {})
    modules = build_viewer_modules(
        session=session,
        state_root=state_root,
        perception_snapshot=perception_snapshot,
        recent_frames=frames,
    )
    normalized_modules = {
        module_name: (
            _with_rendered_image_path(dict(module_payload))
            if isinstance(module_payload, dict)
            else module_payload
        )
        for module_name, module_payload in modules.items()
    }
    primary_module_name = next(iter(normalized_modules.keys()), None)
    primary_module = {} if primary_module_name is None else dict(normalized_modules[primary_module_name] or {})
    latest_frame = primary_module.get("display_frame")
    if latest_frame is None and frames:
        latest_frame = dict(frames[-1])

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
        "modules": normalized_modules,
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read the latest viewer payload directly from persisted runtime truth."
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, follows the current active session.",
    )
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    payload = build_agent_viewer_payload(
        state_root=Path(args.state_root).expanduser().resolve(),
        session_id=args.session_id,
    )
    print(json.dumps(payload, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
