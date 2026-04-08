from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.runtime_session import AgentSession
from backend.session_frames import tracking_recent_frames
from backend.tracking.memory import (
    normalize_tracking_memory,
    tracking_memory_display_text,
    tracking_memory_summary,
)

TRACKING_DIALOGUE_LIMIT = 6


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
    return tracking_recent_frames(
        state_root=Path(session.state_paths["state_root"]),
        session_id=session.session_id,
        raw_session=session.session,
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

    latest_memory = normalize_tracking_memory(raw.get("latest_memory", {}))
    return {
        "target_description": str(raw.get("target_description", "")).strip(),
        "latest_target_id": latest_target_id,
        "latest_target_crop": str(raw.get("latest_target_crop", "")).strip(),
        "latest_front_target_crop": str(raw.get("latest_front_target_crop", "")).strip(),
        "latest_back_target_crop": str(raw.get("latest_back_target_crop", "")).strip(),
        "latest_confirmed_frame_path": str(raw.get("latest_confirmed_frame_path", "")).strip(),
        "identity_target_crop": str(raw.get("identity_target_crop", "")).strip(),
        "latest_confirmed_bbox": raw.get("latest_confirmed_bbox"),
        "init_frame_snapshot": raw.get("init_frame_snapshot"),
        "pending_question": str(raw.get("pending_question", "") or "").strip(),
        "latest_memory": latest_memory,
        "latest_memory_text": tracking_memory_display_text(latest_memory),
        "memory_summary": tracking_memory_summary(latest_memory),
    }


def build_tracking_context(
    session: AgentSession,
    *,
    request_id: str,
    excluded_track_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    tracking_state = tracking_state_snapshot((session.skills.get("tracking") or {}))
    normalized_excluded_track_ids = sorted(_normalized_track_id_set(excluded_track_ids))
    return {
        "session_id": session.session_id,
        "request_id": request_id,
        "target_description": tracking_state.get("target_description", ""),
        "memory": tracking_state.get("latest_memory", ""),
        "latest_target_id": tracking_state.get("latest_target_id"),
        "latest_target_crop": tracking_state.get("latest_target_crop") or None,
        "latest_front_target_crop": tracking_state.get("latest_front_target_crop") or None,
        "latest_back_target_crop": tracking_state.get("latest_back_target_crop") or None,
        "latest_confirmed_frame_path": tracking_state.get("latest_confirmed_frame_path") or None,
        "identity_target_crop": tracking_state.get("identity_target_crop") or None,
        "latest_confirmed_bbox": tracking_state.get("latest_confirmed_bbox"),
        "init_frame_snapshot": tracking_state.get("init_frame_snapshot"),
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
