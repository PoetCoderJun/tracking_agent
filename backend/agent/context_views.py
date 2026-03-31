from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.agent.context import AgentContext
from skills.tracking.memory_format import tracking_memory_display_text, tracking_memory_summary

TRACKING_SKILL_NAME = "tracking"
TRACKING_RUNTIME_NAMESPACE = "tracking_runtime"
ROUTE_DIALOGUE_LIMIT = 6
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


def _latest_user_text(raw_session: Dict[str, Any]) -> str:
    for entry in reversed(list(raw_session.get("conversation_history") or [])):
        if str(entry.get("role", "")).strip() != "user":
            continue
        text = str(entry.get("text", "")).strip()
        if text:
            return text
    return ""


def _recent_frames(
    raw_session: Dict[str, Any],
    *,
    candidate_track_id_floor_exclusive: Optional[int] = None,
) -> List[Dict[str, Any]]:
    frames: List[Dict[str, Any]] = []
    for frame in list(raw_session.get("recent_frames") or []):
        if not isinstance(frame, dict):
            continue
        detections: List[Dict[str, Any]] = []
        for detection in list(frame.get("detections") or []):
            if not isinstance(detection, dict):
                continue
            bbox = detection.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            track_id = int(detection["track_id"])
            if (
                candidate_track_id_floor_exclusive is not None
                and track_id <= int(candidate_track_id_floor_exclusive)
            ):
                continue
            detections.append(
                {
                    "track_id": track_id,
                    "bbox": [int(value) for value in bbox],
                    "score": float(detection.get("score", 1.0)),
                    "label": str(detection.get("label", "person")),
                }
            )
        frames.append(
            {
                "frame_id": str(frame.get("frame_id", "")).strip(),
                "timestamp_ms": int(frame.get("timestamp_ms", 0)),
                "image_path": str(frame.get("image_path", "")).strip(),
                "detections": detections,
            }
        )
    return frames


def _perception_service(context: AgentContext):
    from backend.perception.service import LocalPerceptionService

    return LocalPerceptionService(Path(context.state_paths["state_root"]))


def _recent_frames_from_perception(
    context: AgentContext,
    *,
    candidate_track_id_floor_exclusive: Optional[int] = None,
) -> List[Dict[str, Any]]:
    service = _perception_service(context)
    frames: List[Dict[str, Any]] = []
    for observation in service.recent_camera_observations(session_id=context.session_id):
        payload = dict(observation.get("payload") or {})
        meta = dict(observation.get("meta") or {})
        detections: List[Dict[str, Any]] = []
        for detection in list(meta.get("detections") or []):
            if not isinstance(detection, dict):
                continue
            bbox = detection.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            track_id = int(detection["track_id"])
            if (
                candidate_track_id_floor_exclusive is not None
                and track_id <= int(candidate_track_id_floor_exclusive)
            ):
                continue
            detections.append(
                {
                    "track_id": track_id,
                    "bbox": [int(value) for value in bbox],
                    "score": float(detection.get("score", 1.0)),
                    "label": str(detection.get("label", "person")),
                }
            )
        frames.append(
            {
                "frame_id": str(payload.get("frame_id", observation.get("id", ""))).strip(),
                "timestamp_ms": int(observation.get("ts_ms", 0)),
                "image_path": str(payload.get("image_path", "")).strip(),
                "detections": detections,
            }
        )
    return frames


def _tracking_frames(
    context: AgentContext,
    *,
    candidate_track_id_floor_exclusive: Optional[int] = None,
) -> List[Dict[str, Any]]:
    frames = _recent_frames_from_perception(
        context,
        candidate_track_id_floor_exclusive=candidate_track_id_floor_exclusive,
    )
    if frames:
        return frames
    return _recent_frames(
        context.raw_session,
        candidate_track_id_floor_exclusive=candidate_track_id_floor_exclusive,
    )


def tracking_state_view(context: AgentContext) -> Dict[str, Any]:
    raw = dict((context.skill_cache.get(TRACKING_SKILL_NAME) or {}))
    latest_target_id = raw.get("latest_target_id", raw.get("target_id"))
    if latest_target_id not in (None, ""):
        latest_target_id = int(latest_target_id)
    return {
        "target_description": str(raw.get("target_description", "")).strip(),
        "latest_target_id": latest_target_id,
        "latest_target_crop": str(raw.get("latest_target_crop", "")).strip(),
        "latest_confirmed_frame_path": str(raw.get("latest_confirmed_frame_path", "")).strip(),
        "identity_target_crop": str(raw.get("identity_target_crop", "")).strip(),
        "latest_confirmed_bbox": raw.get("latest_confirmed_bbox"),
        "init_frame_snapshot": raw.get("init_frame_snapshot"),
        "pending_question": str(raw.get("pending_question", "")).strip(),
        "latest_memory": raw.get("latest_memory", ""),
        "latest_memory_text": tracking_memory_display_text(raw.get("latest_memory", "")),
        "memory_summary": tracking_memory_summary(raw.get("latest_memory", "")),
    }


def tracking_runtime_view(context: AgentContext) -> Dict[str, Any]:
    return dict((context.skill_cache.get(TRACKING_RUNTIME_NAMESPACE) or {}))


def build_route_context(
    context: AgentContext,
    *,
    request_id: str,
    enabled_skill_names: List[str],
) -> Dict[str, Any]:
    raw_session = context.raw_session
    frames = _tracking_frames(context)
    latest_frame = None if not frames else frames[-1]
    latest_result = dict(raw_session.get("latest_result") or {})
    tracking_state = tracking_state_view(context)
    return {
        "session_id": context.session_id,
        "request_id": request_id,
        "enabled_skills": list(enabled_skill_names),
        "latest_user_text": _latest_user_text(raw_session),
        "recent_dialogue": _normalized_dialogue(
            raw_session.get("conversation_history"),
            limit=ROUTE_DIALOGUE_LIMIT,
        ),
        "latest_frame": None
        if latest_frame is None
        else {
            "frame_id": latest_frame["frame_id"],
            "timestamp_ms": latest_frame["timestamp_ms"],
            "detection_count": len(latest_frame["detections"]),
        },
        "latest_result": {
            "behavior": latest_result.get("behavior"),
            "frame_id": latest_result.get("frame_id"),
            "target_id": latest_result.get("target_id"),
            "found": latest_result.get("found"),
            "decision": latest_result.get("decision"),
            "text": str(latest_result.get("text", "")).strip(),
            "needs_clarification": latest_result.get("needs_clarification"),
            "clarification_question": latest_result.get("clarification_question"),
        }
        if latest_result
        else None,
        "tracking": {
            "has_active_target": bool(
                tracking_state.get("latest_target_id") is not None
                and tracking_state.get("latest_confirmed_frame_path")
            ),
            "latest_target_id": tracking_state.get("latest_target_id"),
            "target_description": tracking_state.get("target_description"),
            "pending_question": tracking_state.get("pending_question"),
            "memory_summary": tracking_state.get("memory_summary"),
        },
    }


def build_tracking_context(
    context: AgentContext,
    *,
    request_id: str,
    recovery_mode: bool = False,
    missing_target_id: Optional[int] = None,
    candidate_track_id_floor_exclusive: Optional[int] = None,
) -> Dict[str, Any]:
    raw_session = context.raw_session
    tracking_state = tracking_state_view(context)
    return {
        "session_id": context.session_id,
        "request_id": request_id,
        "target_description": tracking_state.get("target_description", ""),
        "memory": tracking_state.get("latest_memory_text", ""),
        "latest_target_id": tracking_state.get("latest_target_id"),
        "latest_target_crop": tracking_state.get("latest_target_crop") or None,
        "latest_confirmed_frame_path": tracking_state.get("latest_confirmed_frame_path") or None,
        "identity_target_crop": tracking_state.get("identity_target_crop") or None,
        "latest_confirmed_bbox": tracking_state.get("latest_confirmed_bbox"),
        "init_frame_snapshot": tracking_state.get("init_frame_snapshot"),
        "chat_history": _normalized_dialogue(
            raw_session.get("conversation_history"),
            limit=TRACKING_DIALOGUE_LIMIT,
        ),
        "recovery_mode": bool(recovery_mode),
        "missing_target_id": None if missing_target_id is None else int(missing_target_id),
        "candidate_track_id_floor_exclusive": (
            None
            if candidate_track_id_floor_exclusive is None
            else int(candidate_track_id_floor_exclusive)
        ),
        "frames": _tracking_frames(
            context,
            candidate_track_id_floor_exclusive=candidate_track_id_floor_exclusive,
        ),
    }
