from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.project_paths import resolve_project_path
from agent.session_store import LiveSessionStore, resolve_session_id
from capabilities.tracking.artifacts.visualization import save_detection_visualization
from interfaces.viewer.skill_modules import build_viewer_modules
from world.perception import recent_frames
from world.perception.service import LocalPerceptionService

VIEWER_DIRNAME = "viewer"
VIEWER_STATE_FILENAME = "latest.json"
VIEWER_FRAME_FILENAME = "latest.jpg"
VIEWER_MEMORY_HISTORY_FILENAME = "memory_history.json"


@dataclass(frozen=True)
class _RenderedDetection:
    track_id: int | None
    bbox: List[int]


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


def _viewer_dir(state_root: Path) -> Path:
    return Path(state_root) / VIEWER_DIRNAME


def viewer_state_path(*, state_root: Path) -> Path:
    return _viewer_dir(state_root) / VIEWER_STATE_FILENAME


def viewer_frame_path(*, state_root: Path) -> Path:
    return _viewer_dir(state_root) / VIEWER_FRAME_FILENAME


def viewer_memory_history_path(*, state_root: Path) -> Path:
    return _viewer_dir(state_root) / VIEWER_MEMORY_HISTORY_FILENAME


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _normalized_track_id(raw_track_id: Any) -> int | None:
    if raw_track_id in (None, ""):
        return None
    try:
        return int(raw_track_id)
    except (TypeError, ValueError):
        return None


def _normalized_bbox(raw_bbox: Any) -> List[int] | None:
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return None
    try:
        return [int(value) for value in raw_bbox]
    except (TypeError, ValueError):
        return None


def _display_frame_ref(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    tracking_module = payload.get("modules", {}).get("tracking")
    if isinstance(tracking_module, dict):
        display_frame = tracking_module.get("display_frame")
        if isinstance(display_frame, dict):
            return display_frame
    latest_frame = payload.get("observation", {}).get("latest_frame")
    return latest_frame if isinstance(latest_frame, dict) else None


def _read_json_file(path: Path) -> Any:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_memory_history(path: Path) -> tuple[str | None, List[Dict[str, Any]]]:
    raw_payload = _read_json_file(path)
    if isinstance(raw_payload, dict):
        session_id = raw_payload.get("session_id")
        raw_history = raw_payload.get("history")
        return (
            None if session_id in (None, "") else str(session_id).strip(),
            list(raw_history) if isinstance(raw_history, list) else [],
        )
    if isinstance(raw_payload, list):
        return None, list(raw_payload)
    return None, []


def _append_memory_snapshot(
    *,
    payload: Dict[str, Any],
    existing_history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    tracking_module = payload.get("modules", {}).get("tracking")
    if not isinstance(tracking_module, dict):
        return existing_history

    memory = str(tracking_module.get("current_memory", "") or "").strip()
    if not memory:
        return existing_history

    next_entry = {
        "updated_at": str(payload.get("updated_at", "") or "").strip(),
        "frame_id": payload.get("summary", {}).get("frame_id", ""),
        "target_id": payload.get("summary", {}).get("target_id"),
        "behavior": ((payload.get("agent", {}) or {}).get("latest_result") or {}).get("behavior", "memory"),
        "memory": memory,
    }
    key = f"{next_entry['updated_at']}|{next_entry['frame_id']}|{next_entry['memory']}"
    if existing_history:
        last = existing_history[-1]
        last_key = f"{last.get('updated_at', '')}|{last.get('frame_id', '')}|{last.get('memory', '')}"
        if last_key == key:
            return existing_history
    return [*existing_history, next_entry]


def _rendered_detections(display_frame: Dict[str, Any]) -> List[_RenderedDetection]:
    detections: List[_RenderedDetection] = []
    for raw_detection in list(display_frame.get("detections") or []):
        if not isinstance(raw_detection, dict):
            continue
        bbox = _normalized_bbox(raw_detection.get("bbox"))
        if bbox is None:
            continue
        detections.append(
            _RenderedDetection(
                track_id=_normalized_track_id(
                    raw_detection.get("track_id", raw_detection.get("target_id"))
                ),
                bbox=bbox,
            )
        )
    return detections


def _render_latest_frame(
    *,
    state_root: Path,
    payload: Dict[str, Any],
) -> Path | None:
    display_frame = _display_frame_ref(payload)
    if display_frame is None:
        return None

    source_path_raw = str(display_frame.get("image_path", "") or "").strip()
    if not source_path_raw:
        return None

    source_path = resolve_project_path(source_path_raw)
    if not source_path.exists() or not source_path.is_file():
        return None

    output_path = viewer_frame_path(state_root=state_root)
    save_detection_visualization(
        source_path,
        _rendered_detections(display_frame),
        output_path,
        highlighted_track_id=_normalized_track_id(
            display_frame.get("target_id", payload.get("summary", {}).get("target_id"))
        ),
    )
    return output_path


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
    frames = recent_frames(state_root=state_root)
    latest_result = dict(session.get("latest_result") or {})
    modules = build_viewer_modules(
        session=session,
        state_root=state_root,
        perception_snapshot=perception_snapshot,
        recent_frames=frames,
    )
    primary_module_name = next(iter(modules.keys()), None)
    primary_module = {} if primary_module_name is None else dict(modules[primary_module_name] or {})
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


def write_agent_viewer_snapshot(
    *,
    state_root: Path,
    session_id: str | None = None,
    output_path: Path | None = None,
) -> Dict[str, Any]:
    resolved_state_root = resolve_project_path(state_root)
    payload = build_agent_viewer_payload(
        state_root=resolved_state_root,
        session_id=session_id,
    )
    memory_history_path = viewer_memory_history_path(state_root=resolved_state_root)
    payload_session_id = None if payload.get("session_id") in (None, "") else str(payload.get("session_id")).strip()
    existing_session_id, normalized_memory_history = _load_memory_history(memory_history_path)
    if payload_session_id and existing_session_id and payload_session_id != existing_session_id:
        normalized_memory_history = []
    updated_memory_history = _append_memory_snapshot(
        payload=payload,
        existing_history=normalized_memory_history,
    )
    tracking_module = payload.get("modules", {}).get("tracking")
    if isinstance(tracking_module, dict):
        tracking_module["memory_history"] = updated_memory_history

    rendered_frame = _render_latest_frame(
        state_root=resolved_state_root,
        payload=payload,
    )
    display_frame = _display_frame_ref(payload)
    if display_frame is not None:
        display_frame["rendered_image_path"] = (
            None if rendered_frame is None else str(rendered_frame.resolve())
        )

    resolved_output_path = (
        viewer_state_path(state_root=resolved_state_root)
        if output_path is None
        else resolve_project_path(output_path)
    )
    payload["artifacts"] = {
        "viewer_state_path": str(resolved_output_path.resolve()),
        "viewer_frame_path": None if rendered_frame is None else str(rendered_frame.resolve()),
    }
    _write_json_atomic(
        memory_history_path,
        {
            "session_id": payload_session_id,
            "history": updated_memory_history,
        },
    )
    _write_json_atomic(resolved_output_path, payload)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write the latest viewer snapshot from local runtime state."
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, follows the current active session.",
    )
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path. Defaults to <state-root>/viewer/latest.json.",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    payload = write_agent_viewer_snapshot(
        state_root=resolve_project_path(args.state_root),
        session_id=args.session_id,
        output_path=None if args.output in (None, "") else resolve_project_path(args.output),
    )
    print(
        json.dumps(
            {
                "session_id": payload.get("session_id"),
                "available": bool(payload.get("available")),
                "viewer_state_path": payload.get("artifacts", {}).get("viewer_state_path"),
                "viewer_frame_path": payload.get("artifacts", {}).get("viewer_frame_path"),
            },
            ensure_ascii=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
