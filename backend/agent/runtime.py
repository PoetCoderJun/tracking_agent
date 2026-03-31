from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.agent.context import AgentContext
from backend.agent.memory import AgentMemoryStore
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


def _runtime_result_payload(raw_session: Dict[str, Any]) -> Dict[str, Any]:
    latest_result = raw_session.get("latest_result")
    if not isinstance(latest_result, dict):
        return {
            "has_latest_result": False,
            "latest_behavior": None,
            "latest_frame_id": None,
            "latest_target_id": None,
            "latest_found": None,
            "latest_decision": None,
            "latest_text": "",
        }

    return {
        "has_latest_result": True,
        "latest_behavior": latest_result.get("behavior"),
        "latest_frame_id": latest_result.get("frame_id"),
        "latest_target_id": latest_result.get("target_id"),
        "latest_found": latest_result.get("found"),
        "latest_decision": latest_result.get("decision"),
        "latest_text": str(latest_result.get("text", "")).strip(),
    }


class LocalAgentRuntime:
    def __init__(self, state_root: Path, frame_buffer_size: int = 3):
        self._state_root = state_root
        self._store = LiveSessionStore(state_root=state_root, frame_buffer_size=frame_buffer_size)

    @property
    def state_root(self) -> Path:
        return self._state_root

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
                "runtime": _runtime_result_payload(context.raw_session),
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
            {"runtime": _runtime_result_payload(self.context(session_id).raw_session)},
        )
        return self.context(session_id)

    def reset_context(self, session_id: str) -> AgentContext:
        self._store.reset_session_context(session_id)
        self.update_perception_cache(
            session_id,
            {"runtime": _runtime_result_payload(self.context(session_id).raw_session)},
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
