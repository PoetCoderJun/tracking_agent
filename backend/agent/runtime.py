from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.agent.context import AgentContext
from backend.agent.memory import AgentMemoryStore
from backend.perception.stream import RobotIngestEvent
from backend.persistence import LiveSessionStore


def _latest_language_payload(raw_session: Dict[str, Any]) -> Dict[str, Any]:
    history = raw_session.get("conversation_history") or []
    latest_text = ""
    latest_role = None
    if history:
        latest = history[-1]
        latest_text = str(latest.get("text", "")).strip()
        latest_role = str(latest.get("role", "")).strip() or None
    return {
        "latest_role": latest_role,
        "latest_text": latest_text,
        "latest_request_function": raw_session.get("latest_request_function"),
        "latest_request_id": raw_session.get("latest_request_id"),
    }


class LocalAgentRuntime:
    def __init__(self, state_root: Path, frame_buffer_size: int = 3):
        self._state_root = state_root
        self._store = LiveSessionStore(state_root=state_root, frame_buffer_size=frame_buffer_size)

    def _memory_store(self, session_id: str) -> AgentMemoryStore:
        return AgentMemoryStore(self._state_root, session_id)

    def _ensure_session(self, session_id: str, device_id: str = "") -> None:
        self._store.load_or_create_session(session_id=session_id, device_id=device_id)
        self._memory_store(session_id).load_or_create()

    def _state_paths(self, session_id: str) -> Dict[str, str]:
        memory_store = self._memory_store(session_id)
        return {
            "state_root": str(self._state_root.resolve()),
            "session_dir": str(self._store.session_dir(session_id).resolve()),
            "session_path": str(self._store.session_path(session_id).resolve()),
            "agent_memory_path": str(memory_store.path().resolve()),
        }

    def context(self, session_id: str, *, device_id: str = "") -> AgentContext:
        self._ensure_session(session_id, device_id=device_id)
        raw_session = self._store.session_payload(session_id)
        memory = self._memory_store(session_id).load_or_create()
        return AgentContext(
            session_id=session_id,
            raw_session=raw_session,
            user_preferences=memory.user_preferences,
            environment_map=memory.environment_map,
            perception_cache=memory.perception_cache,
            skill_cache=memory.skill_cache,
            state_paths=self._state_paths(session_id),
        )

    def start_fresh_session(self, session_id: str, *, device_id: str = "") -> AgentContext:
        self._store.start_fresh_session(session_id=session_id, device_id=device_id)
        self._memory_store(session_id).reset()
        return self.context(session_id, device_id=device_id)

    def ingest_event(
        self,
        event: RobotIngestEvent,
        *,
        request_id: Optional[str] = None,
        request_function: str = "event",
        frame_payload: Optional[Dict[str, Any]] = None,
        record_conversation: Optional[bool] = None,
    ) -> AgentContext:
        should_record_conversation = (
            request_function.strip().lower() != "observation"
            if record_conversation is None
            else bool(record_conversation)
        )
        stored_session = self._store.ingest_robot_event(
            session_id=event.session_id,
            device_id=event.device_id,
            frame=(
                dict(frame_payload)
                if frame_payload is not None
                else {
                    "frame_id": event.frame.frame_id,
                    "timestamp_ms": event.frame.timestamp_ms,
                    "image_path": event.frame.image_path,
                }
            ),
            detections=[
                {
                    "track_id": detection.track_id,
                    "bbox": list(detection.bbox),
                    "score": detection.score,
                    "label": detection.label,
                }
                for detection in event.detections
            ],
            text=event.text,
            request_id=request_id,
            request_function=request_function,
            record_conversation=should_record_conversation,
        )
        latest_frame = stored_session.recent_frames[-1] if stored_session.recent_frames else None
        self.update_perception_cache(
            event.session_id,
            {
                "vision": {
                    "latest_frame_id": None if latest_frame is None else latest_frame.frame_id,
                    "latest_image_path": None if latest_frame is None else latest_frame.image_path,
                    "latest_detection_count": len(event.detections),
                },
                "language": {
                    "latest_text": event.text,
                    "latest_function": request_function,
                    "latest_request_id": request_id,
                },
            },
        )
        return self.context(event.session_id, device_id=event.device_id)

    def append_chat_request(
        self,
        *,
        session_id: str,
        device_id: str,
        text: str,
        request_id: str,
    ) -> AgentContext:
        self._store.append_chat_request(
            session_id=session_id,
            device_id=device_id,
            text=text,
            request_id=request_id,
        )
        self.update_perception_cache(
            session_id,
            {
                "language": {
                    "latest_text": text,
                    "latest_function": "chat",
                    "latest_request_id": request_id,
                }
            },
        )
        return self.context(session_id, device_id=device_id)

    def apply_skill_result(self, session_id: str, result: Dict[str, Any]) -> AgentContext:
        self._store.apply_agent_result(session_id, result)
        context = self.context(session_id)
        self.update_perception_cache(
            session_id,
            {
                "runtime": {
                    "latest_result": context.raw_session.get("latest_result"),
                },
                "language": _latest_language_payload(context.raw_session),
            },
        )
        return self.context(session_id)

    def patch_latest_result(
        self,
        *,
        session_id: str,
        patch: Dict[str, Any],
        expected_request_id: Optional[str] = None,
        expected_frame_id: Optional[str] = None,
    ) -> AgentContext:
        self._store.patch_latest_result(
            session_id=session_id,
            patch=patch,
            expected_request_id=expected_request_id,
            expected_frame_id=expected_frame_id,
        )
        self.update_perception_cache(
            session_id,
            {
                "runtime": {
                    "latest_result": self.context(session_id).raw_session.get("latest_result"),
                }
            },
        )
        return self.context(session_id)

    def reset_context(self, session_id: str) -> AgentContext:
        self._store.reset_session_context(session_id)
        self.update_perception_cache(
            session_id,
            {
                "runtime": {
                    "latest_result": self.context(session_id).raw_session.get("latest_result"),
                }
            },
        )
        return self.context(session_id)

    def update_user_preferences(self, session_id: str, preferences: Dict[str, Any]) -> AgentContext:
        self._ensure_session(session_id)
        self._memory_store(session_id).update_user_preferences(preferences)
        return self.context(session_id)

    def update_environment_map(self, session_id: str, environment_map: Dict[str, Any]) -> AgentContext:
        self._ensure_session(session_id)
        self._memory_store(session_id).update_environment_map(environment_map)
        return self.context(session_id)

    def update_perception_cache(self, session_id: str, payload: Dict[str, Any]) -> AgentContext:
        self._ensure_session(session_id)
        self._memory_store(session_id).update_perception_cache(payload)
        return self.context(session_id)

    def update_skill_cache(
        self,
        session_id: str,
        *,
        skill_name: str,
        payload: Dict[str, Any],
    ) -> AgentContext:
        self._ensure_session(session_id)
        self._memory_store(session_id).update_skill_cache(skill_name, payload)
        return self.context(session_id)
