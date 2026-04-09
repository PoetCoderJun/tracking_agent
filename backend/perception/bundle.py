from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from backend.perception.frames import recent_frames
from backend.runtime_session import AgentSession


def _latest_user_text(session_payload: Dict[str, Any]) -> str:
    history = session_payload.get("conversation_history") or []
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
    system1: Dict[str, Any]
    language: Dict[str, Any]
    memory: Dict[str, Any]
    user_preferences: Dict[str, Any]
    environment_map: Dict[str, Any]


RobotPerceptionBundle = PerceptionBundle


def build_perception_bundle(session: AgentSession) -> PerceptionBundle:
    state_root = Path(session.state_paths["state_root"])
    frames = recent_frames(state_root=state_root)
    latest_frame = None if not frames else frames[-1]
    perception_snapshot = session.perception_snapshot
    return PerceptionBundle(
        vision={
            "latest_frame": latest_frame,
            "recent_frames": frames,
        },
        system1={
            "latest_frame_result": perception_snapshot.get("latest_frame_result"),
            "recent_frame_results": list(perception_snapshot.get("recent_frame_results") or []),
            "stream_status": dict(perception_snapshot.get("stream_status") or {}),
            "model": dict(perception_snapshot.get("model") or {}),
        },
        language={
            "latest_request_function": session.session.get("latest_request_function"),
            "latest_request_id": session.session.get("latest_request_id"),
            "latest_user_text": _latest_user_text(session.session),
            "recent_dialogue": [
                {
                    "role": str(entry.get("role", "")).strip(),
                    "text": str(entry.get("text", "")).strip(),
                    "timestamp": str(entry.get("timestamp", "")).strip(),
                }
                for entry in list(session.session.get("conversation_history") or [])[-6:]
                if isinstance(entry, dict)
            ],
        },
        memory={
            "latest_result": dict(session.session.get("latest_result") or {}) or None,
        },
        user_preferences=dict(session.user_preferences),
        environment_map=dict(session.environment),
    )
