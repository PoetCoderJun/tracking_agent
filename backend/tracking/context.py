from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.perception.frames import observation_recent_frames
from backend.runtime_session import AgentSession
from backend.tracking.memory import (
    read_tracking_memory_snapshot,
    tracking_memory_display_text,
    tracking_memory_summary,
)

TRACKING_DIALOGUE_LIMIT = 6
TRACKING_LIFECYCLE_INACTIVE = "inactive"
TRACKING_LIFECYCLE_SCHEDULED = "scheduled"
TRACKING_LIFECYCLE_RUNNING = "running"
TRACKING_LIFECYCLE_BOUND = "bound"
TRACKING_LIFECYCLE_SEEKING = "seeking"
TRACKING_LIFECYCLE_STOPPED = "stopped"


def _normalized_dialogue(history: Any, *, limit: int) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for entry in list(history or [])[-limit:]:
        if not isinstance(entry, dict):
            continue
        normalized.append(
            {
                "role": str(entry.get("role", "")).strip(),
                "text": str(entry.get("text", "")).strip(),
                "timestamp": str(entry.get("timestamp", "")).strip(),
            }
        )
    return normalized


def _tracking_frames(
    session: AgentSession,
    *,
    excluded_track_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    return observation_recent_frames(
        state_root=Path(session.state_paths["state_root"]),
        excluded_track_ids=excluded_track_ids,
    )


def _normalized_track_id_set(raw_track_ids: Any) -> set[int]:
    normalized: set[int] = set()
    for track_id in list(raw_track_ids or []):
        try:
            normalized.add(int(track_id))
        except (TypeError, ValueError):
            continue
    return normalized


def tracking_state_snapshot(raw_tracking_state: Any) -> Dict[str, Any]:
    raw = dict(raw_tracking_state or {})
    latest_target_id = raw.get("latest_target_id")
    if latest_target_id not in (None, ""):
        latest_target_id = int(latest_target_id)

    lifecycle_status = str(raw.get("lifecycle_status", "") or "").strip()
    if not lifecycle_status:
        if str(raw.get("pending_question", "") or "").strip():
            lifecycle_status = TRACKING_LIFECYCLE_SEEKING
        elif latest_target_id is not None:
            lifecycle_status = TRACKING_LIFECYCLE_BOUND
        else:
            lifecycle_status = TRACKING_LIFECYCLE_INACTIVE
    return {
        "target_description": str(raw.get("target_description", "")).strip(),
        "latest_target_id": latest_target_id,
        "pending_question": str(raw.get("pending_question", "") or "").strip(),
        "lifecycle_status": lifecycle_status,
        "generation": int(raw.get("generation", 0) or 0),
        "next_tracking_turn_at": raw.get("next_tracking_turn_at"),
        "last_seen_frame_id": str(raw.get("last_seen_frame_id", "") or "").strip(),
        "last_completed_frame_id": str(raw.get("last_completed_frame_id", "") or "").strip(),
        "last_trigger": str(raw.get("last_trigger", "") or "").strip(),
        "stop_reason": str(raw.get("stop_reason", "") or "").strip(),
    }


def build_tracking_context(
    session: AgentSession,
    *,
    request_id: str,
    excluded_track_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    tracking_state = tracking_state_snapshot((session.skills.get("tracking") or {}))
    memory_snapshot = read_tracking_memory_snapshot(
        state_root=Path(session.state_paths["state_root"]),
        session_id=session.session_id,
    )
    latest_memory = memory_snapshot["memory"]
    normalized_excluded_track_ids = sorted(_normalized_track_id_set(excluded_track_ids))
    return {
        "session_id": session.session_id,
        "request_id": request_id,
        "target_description": tracking_state.get("target_description", ""),
        "memory": latest_memory,
        "front_crop_path": memory_snapshot["front_crop_path"] or None,
        "back_crop_path": memory_snapshot["back_crop_path"] or None,
        "memory_text": tracking_memory_display_text(latest_memory),
        "memory_summary": tracking_memory_summary(latest_memory),
        "latest_target_id": tracking_state.get("latest_target_id"),
        "chat_history": _normalized_dialogue(
            session.session.get("conversation_history"),
            limit=TRACKING_DIALOGUE_LIMIT,
        ),
        "excluded_track_ids": normalized_excluded_track_ids,
        "frames": _tracking_frames(
            session,
            excluded_track_ids=normalized_excluded_track_ids,
        ),
    }
