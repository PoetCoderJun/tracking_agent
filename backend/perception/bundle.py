from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from backend.agent.context import AgentContext
from backend.agent.context_views import build_route_context, tracking_state_view
from backend.perception.service import LocalPerceptionService


def _latest_user_text(raw_session: Dict[str, Any]) -> str:
    history = raw_session.get("conversation_history") or []
    for entry in reversed(history):
        if str(entry.get("role", "")).strip() != "user":
            continue
        text = str(entry.get("text", "")).strip()
        if text:
            return text
    return ""


@dataclass(frozen=True)
class PerceptionBundle:
    vision: Dict[str, Any]
    language: Dict[str, Any]
    memory: Dict[str, Any]
    user_preferences: Dict[str, Any]
    environment_map: Dict[str, Any]


RobotPerceptionBundle = PerceptionBundle


def build_perception_bundle(context: AgentContext) -> PerceptionBundle:
    raw_session = context.raw_session
    perception = LocalPerceptionService(Path(context.state_paths["state_root"]))
    recent_frames = [
        {
            "frame_id": str((item.get("payload") or {}).get("frame_id", item.get("id", ""))).strip(),
            "timestamp_ms": int(item.get("ts_ms", 0)),
            "image_path": str((item.get("payload") or {}).get("image_path", "")).strip(),
            "detections": list((item.get("meta") or {}).get("detections") or []),
        }
        for item in perception.recent_camera_observations(session_id=context.session_id)
    ]
    latest_frame = None if not recent_frames else recent_frames[-1]
    route_context = build_route_context(
        context,
        request_id=str(raw_session.get("latest_request_id", "") or ""),
        enabled_skill_names=[],
    )
    tracking_state = tracking_state_view(context)
    return PerceptionBundle(
        vision={
            "latest_frame": latest_frame,
            "recent_frames": recent_frames,
        },
        language={
            "latest_request_function": raw_session.get("latest_request_function"),
            "latest_request_id": raw_session.get("latest_request_id"),
            "latest_user_text": _latest_user_text(raw_session),
            "recent_dialogue": list(route_context.get("recent_dialogue") or []),
        },
        memory={
            "latest_result": route_context.get("latest_result"),
            "runtime_summary": dict((context.perception_cache.get("runtime") or {})),
            "tracking_summary": {
                "latest_target_id": tracking_state.get("latest_target_id"),
                "pending_question": tracking_state.get("pending_question"),
                "memory_summary": tracking_state.get("memory_summary"),
            },
        },
        user_preferences=dict(context.user_preferences),
        environment_map=dict(context.environment_map),
    )
