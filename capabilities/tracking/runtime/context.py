from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.state.session import AgentSession
from capabilities.tracking.runtime.types import TrackingObservation, TrackingState, TrackingTrigger
from capabilities.tracking.state.memory import (
    empty_tracking_memory,
    read_tracking_memory_snapshot,
    tracking_memory_display_text,
    tracking_memory_summary,
)
from world.perception import recent_frames

TRACKING_LIFECYCLE_INACTIVE = "inactive"
TRACKING_LIFECYCLE_SCHEDULED = "scheduled"
TRACKING_LIFECYCLE_RUNNING = "running"
TRACKING_LIFECYCLE_BOUND = "bound"
TRACKING_LIFECYCLE_SEEKING = "seeking"
TRACKING_LIFECYCLE_STOPPED = "stopped"
TRACKING_SKILL_NAME = "tracking-init"


def _normalized_track_id_set(raw_track_ids: Any) -> set[int]:
    normalized: set[int] = set()
    for track_id in list(raw_track_ids or []):
        try:
            normalized.add(int(track_id))
        except (TypeError, ValueError):
            continue
    return normalized


def normalize_tracking_state(raw_tracking_state: Any) -> TrackingState:
    raw = dict(raw_tracking_state or {})
    latest_target_id = raw.get("latest_target_id")
    if latest_target_id not in (None, ""):
        latest_target_id = int(latest_target_id)
    else:
        latest_target_id = None

    lifecycle_status = str(raw.get("lifecycle_status", "") or "").strip()
    if not lifecycle_status:
        if str(raw.get("pending_question", "") or "").strip():
            lifecycle_status = TRACKING_LIFECYCLE_SEEKING
        elif latest_target_id is not None:
            lifecycle_status = TRACKING_LIFECYCLE_BOUND
        else:
            lifecycle_status = TRACKING_LIFECYCLE_INACTIVE

    return TrackingState(
        target_description=str(raw.get("target_description", "")).strip(),
        latest_target_id=latest_target_id,
        pending_question=str(raw.get("pending_question", "") or "").strip(),
        lifecycle_status=lifecycle_status,
        generation=int(raw.get("generation", 0) or 0),
        last_completed_frame_id=str(raw.get("last_completed_frame_id", "") or "").strip(),
        last_reviewed_trigger=str(raw.get("last_reviewed_trigger", "") or raw.get("last_trigger", "") or "").strip(),
        last_reviewed_cause=str(raw.get("last_reviewed_cause", "") or "").strip(),
        stop_reason=str(raw.get("stop_reason", "") or "").strip(),
    )


def tracking_state_snapshot(raw_tracking_state: Any) -> Dict[str, Any]:
    state = normalize_tracking_state(raw_tracking_state)
    return {
        "target_description": state.target_description,
        "latest_target_id": state.latest_target_id,
        "pending_question": state.pending_question,
        "lifecycle_status": state.lifecycle_status,
        "generation": state.generation,
        "last_completed_frame_id": state.last_completed_frame_id,
        "last_reviewed_trigger": state.last_reviewed_trigger,
        "last_reviewed_cause": state.last_reviewed_cause,
        "stop_reason": state.stop_reason,
    }


def build_tracking_observation(
    session: AgentSession,
    *,
    trigger: TrackingTrigger,
    excluded_track_ids: Optional[List[int]] = None,
) -> TrackingObservation:
    state = normalize_tracking_state(session.capabilities.get(TRACKING_SKILL_NAME))
    memory_snapshot = read_tracking_memory_snapshot(
        state_root=Path(session.state_paths["state_root"]),
        session_id=session.session_id,
    )
    normalized_excluded_track_ids = sorted(_normalized_track_id_set(excluded_track_ids))
    frames = recent_frames(
        state_root=Path(session.state_paths["state_root"]),
        excluded_track_ids=normalized_excluded_track_ids,
    )
    latest_frame = frames[-1] if frames else {}
    return TrackingObservation(
        session_id=session.session_id,
        trigger=trigger,
        state=state,
        memory=dict(memory_snapshot["memory"]),
        latest_frame=dict(latest_frame),
        recent_frames=list(frames),
        front_crop_path=memory_snapshot["front_crop_path"] or None,
        back_crop_path=memory_snapshot["back_crop_path"] or None,
    )


def build_tracking_init_context(
    session: AgentSession,
    *,
    request_id: str,
    excluded_track_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    state = normalize_tracking_state(session.capabilities.get(TRACKING_SKILL_NAME))
    memory_snapshot = read_tracking_memory_snapshot(
        state_root=Path(session.state_paths["state_root"]),
        session_id=session.session_id,
    )
    normalized_excluded_track_ids = sorted(_normalized_track_id_set(excluded_track_ids))
    return {
        "session_id": session.session_id,
        "request_id": request_id,
        "target_description": state.target_description,
        "memory": memory_snapshot["memory"] or empty_tracking_memory(),
        "front_crop_path": memory_snapshot["front_crop_path"] or None,
        "back_crop_path": memory_snapshot["back_crop_path"] or None,
        "memory_text": tracking_memory_display_text(memory_snapshot["memory"]),
        "memory_summary": tracking_memory_summary(memory_snapshot["memory"]),
        "latest_target_id": state.latest_target_id,
        "excluded_track_ids": normalized_excluded_track_ids,
        "frames": recent_frames(
            state_root=Path(session.state_paths["state_root"]),
            excluded_track_ids=normalized_excluded_track_ids,
        ),
    }


def build_tracking_context(
    session: AgentSession,
    *,
    request_id: str,
    excluded_track_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    return build_tracking_init_context(
        session,
        request_id=request_id,
        excluded_track_ids=excluded_track_ids,
    )
