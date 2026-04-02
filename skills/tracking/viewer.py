from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.project_paths import resolve_project_path
from skills.tracking.core.context import tracking_state_snapshot


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


def _target_bbox(
    *,
    latest_result: Dict[str, Any],
    tracking_state: Dict[str, Any],
    display_frame: Dict[str, Any],
) -> Optional[List[int]]:
    bbox = latest_result.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        return [int(value) for value in bbox]

    target_id = latest_result.get("target_id")
    if target_id in (None, ""):
        target_id = tracking_state.get("latest_target_id")
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


def _tracking_status(
    *,
    latest_result: Dict[str, Any],
    tracking_state: Dict[str, Any],
    stream_status: Dict[str, Any],
) -> Dict[str, str]:
    if str(stream_status.get("status", "")).strip() == "completed":
        return {"kind": "completed", "label": "视频结束"}

    pending_question = str(tracking_state.get("pending_question", "") or "").strip()
    if pending_question:
        return {"kind": "seeking", "label": "寻找中"}

    action = (
        ((latest_result.get("robot_response") or {}).get("action"))
        if isinstance(latest_result.get("robot_response"), dict)
        else None
    )
    if action in (None, ""):
        action = latest_result.get("decision") or latest_result.get("behavior")

    if action == "wait":
        return {"kind": "seeking", "label": "寻找中"}
    if (
        action in {"track", "init"}
        or latest_result.get("behavior") in {"init", "track"}
        or latest_result.get("target_id") not in (None, "")
    ):
        return {"kind": "tracking", "label": "跟踪中"}
    return {"kind": "idle", "label": "等待中"}


def build_viewer_module(
    *,
    session: Dict[str, Any],
    state_root: Path,
    perception_snapshot: Dict[str, Any],
    recent_frames: list[Dict[str, Any]],
) -> Dict[str, Any] | None:
    _ = state_root
    tracking_state = tracking_state_snapshot((session.get("skill_cache") or {}).get("tracking"))
    if not tracking_state and not (session.get("latest_result") or {}):
        return None

    latest_result = dict(session.get("latest_result") or {})
    stream_status = dict(perception_snapshot.get("stream_status") or {})
    status = _tracking_status(
        latest_result=latest_result,
        tracking_state=tracking_state,
        stream_status=stream_status,
    )

    resolved_target_id = latest_result.get("target_id")
    if resolved_target_id in (None, ""):
        resolved_target_id = tracking_state.get("latest_target_id")

    display_frame = None
    if recent_frames and resolved_target_id not in (None, ""):
        display_frame = dict(recent_frames[-1])

    display_frame_payload = None
    if display_frame is not None:
        display_frame_payload = {
            **display_frame,
            "target_id": resolved_target_id,
            "bbox": _target_bbox(
                latest_result=latest_result,
                tracking_state=tracking_state,
                display_frame=display_frame,
            ),
            "image_data_url": _image_data_url(display_frame.get("image_path")),
        }

    return {
        "enabled": True,
        "target_id": tracking_state.get("latest_target_id"),
        "pending_question": tracking_state.get("pending_question"),
        "status_kind": status["kind"],
        "status_label": status["label"],
        "current_memory": tracking_state.get("latest_memory_text", ""),
        "memory_history": [],
        "display_frame": display_frame_payload,
    }
