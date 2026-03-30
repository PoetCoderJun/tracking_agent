from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from backend.agent.context import AgentContext


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
    recent_frames = list(raw_session.get("recent_frames") or [])
    latest_frame = None if not recent_frames else recent_frames[-1]
    latest_result = raw_session.get("latest_result") or {}
    return PerceptionBundle(
        vision={
            "latest_frame": latest_frame,
            "recent_frames": recent_frames,
        },
        language={
            "latest_request_function": raw_session.get("latest_request_function"),
            "latest_request_id": raw_session.get("latest_request_id"),
            "latest_user_text": _latest_user_text(raw_session),
            "conversation_history": list(raw_session.get("conversation_history") or []),
        },
        memory={
            "latest_result_memory": str(latest_result.get("memory", "")),
            "latest_result": latest_result or None,
            "skill_cache": dict(context.skill_cache),
            "perception_cache": dict(context.perception_cache),
        },
        user_preferences=dict(context.user_preferences),
        environment_map=dict(context.environment_map),
    )
