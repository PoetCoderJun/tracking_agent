from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from world.perception.service import LocalPerceptionService
from agent.session import AgentSession
from capabilities.tracking.context import TRACKING_LIFECYCLE_SEEKING, normalize_tracking_state
from capabilities.tracking.types import (
    TRIGGER_CADENCE_REVIEW,
    TRIGGER_EVENT_REBIND,
    TrackingTrigger,
)


def latest_tracking_frame(session: AgentSession) -> Dict[str, Any]:
    latest_observation = LocalPerceptionService(Path(session.state_paths["state_root"])).latest_camera_observation()
    if latest_observation is None:
        return {}
    payload = dict(latest_observation.get("payload") or {})
    meta = dict(latest_observation.get("meta") or {})
    return {
        "frame_id": str(payload.get("frame_id", latest_observation.get("id", ""))).strip(),
        "timestamp_ms": int(latest_observation.get("ts_ms", 0)),
        "image_path": str(payload.get("image_path", "")).strip(),
        "detections": list(meta.get("detections") or []),
    }


def _track_id_present(frame: Dict[str, Any], target_id: int | None) -> bool:
    if target_id is None:
        return False
    for detection in list(frame.get("detections") or []):
        try:
            if int(detection.get("track_id")) == int(target_id):
                return True
        except (TypeError, ValueError):
            continue
    return False


def derive_continuous_trigger(
    session: AgentSession,
    *,
    now_seconds: float | None = None,
) -> TrackingTrigger | None:
    state = normalize_tracking_state(session.capabilities.get("tracking"))
    if state.latest_target_id is None:
        return None
    if state.pending_question:
        return None

    latest_frame = latest_tracking_frame(session)
    frame_id = str(latest_frame.get("frame_id", "")).strip() or None
    if frame_id is None:
        return None

    target_present = _track_id_present(latest_frame, state.latest_target_id)
    request_id = str(session.session.get("latest_request_id", "") or "").strip() or f"tracking:{session.session_id}:{frame_id}"
    if not target_present and frame_id != state.last_completed_frame_id:
        return TrackingTrigger(
            type=TRIGGER_EVENT_REBIND,
            cause="target_missing",
            frame_id=frame_id,
            request_id=request_id,
            source="tracking_loop",
        )
    if target_present and frame_id != state.last_completed_frame_id:
        return TrackingTrigger(
            type=TRIGGER_CADENCE_REVIEW,
            cause="new_snapshot",
            frame_id=frame_id,
            request_id=request_id,
            source="tracking_loop",
        )
    return None


def tracking_runtime_status(session: AgentSession) -> Dict[str, Any]:
    state = normalize_tracking_state(session.capabilities.get("tracking"))
    frame = latest_tracking_frame(session)
    frame_id = str(frame.get("frame_id", "")).strip() or None
    target_present = _track_id_present(frame, state.latest_target_id)
    if state.latest_target_id is None:
        return {"status": "idle", "frame_id": frame_id, "target_present": False}
    if state.pending_question:
        return {"status": "waiting", "frame_id": frame_id, "target_present": target_present}
    if target_present:
        return {"status": "bound", "frame_id": frame_id, "target_present": True}
    if state.lifecycle_status == TRACKING_LIFECYCLE_SEEKING:
        return {"status": "seeking", "frame_id": frame_id, "target_present": False}
    return {"status": "seeking", "frame_id": frame_id, "target_present": False}
