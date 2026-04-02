from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from backend.agent.context import AgentContext
from backend.session_frames import observation_recent_frames


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
    recent_frames = observation_recent_frames(
        state_root=Path(context.state_paths["state_root"]),
        session_id=context.session_id,
    )
    latest_frame = None if not recent_frames else recent_frames[-1]
    return PerceptionBundle(
        vision={
            "latest_frame": latest_frame,
            "recent_frames": recent_frames,
        },
        language={
            "latest_request_function": raw_session.get("latest_request_function"),
            "latest_request_id": raw_session.get("latest_request_id"),
            "latest_user_text": _latest_user_text(raw_session),
            "recent_dialogue": [
                {
                    "role": str(entry.get("role", "")).strip(),
                    "text": str(entry.get("text", "")).strip(),
                    "timestamp": str(entry.get("timestamp", "")).strip(),
                }
                for entry in list(raw_session.get("conversation_history") or [])[-6:]
                if isinstance(entry, dict)
            ],
        },
        memory={
            "latest_result": dict(raw_session.get("latest_result") or {}) or None,
            "runtime_summary": dict((context.perception_cache.get("runtime") or {})),
        },
        user_preferences=dict(context.user_preferences),
        environment_map=dict(context.environment_map),
    )
