from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.agent.session import AgentSession
from backend.persistence import LiveSessionStore


def _latest_language_snapshot(session: Dict[str, Any]) -> Dict[str, Any]:
    history = session.get("conversation_history") or []
    latest_text = ""
    latest_role = None
    if history:
        latest = history[-1]
        latest_text = str(latest.get("text", "")).strip()
        latest_role = str(latest.get("role", "")).strip() or None
    return {
        "latest_role": latest_role,
        "latest_text": latest_text,
        "latest_request_function": session.get("latest_request_function"),
        "latest_request_id": session.get("latest_request_id"),
    }


def _runtime_result_snapshot(session: Dict[str, Any]) -> Dict[str, Any]:
    latest_result = session.get("latest_result")
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


class AgentSessionStore:
    def __init__(self, state_root: Path, frame_buffer_size: int = 3):
        self._state_root = state_root
        self._store = LiveSessionStore(state_root=state_root, frame_buffer_size=frame_buffer_size)

    @property
    def state_root(self) -> Path:
        return self._state_root

    def _ensure_session(self, session_id: str, device_id: str = "") -> None:
        self._store.load_or_create_session(session_id=session_id, device_id=device_id)

    def _state_paths(self, session_id: str) -> Dict[str, str]:
        session_path = self._store.session_path(session_id).resolve()
        return {
            "state_root": str(self._state_root.resolve()),
            "session_dir": str(self._store.session_dir(session_id).resolve()),
            "session_path": str(session_path),
        }

    def load(self, session_id: str, *, device_id: str = "") -> AgentSession:
        self._ensure_session(session_id, device_id=device_id)
        return AgentSession(
            payload=self._store.session_payload(session_id),
            state_paths=self._state_paths(session_id),
        )

    def start_fresh_session(self, session_id: str, *, device_id: str = "") -> AgentSession:
        self._store.start_fresh_session(session_id=session_id, device_id=device_id)
        return self.load(session_id, device_id=device_id)

    def append_chat_request(
        self,
        *,
        session_id: str,
        device_id: str,
        text: str,
        request_id: str,
    ) -> AgentSession:
        self._store.append_chat_request(
            session_id=session_id,
            device_id=device_id,
            text=text,
            request_id=request_id,
        )
        self.patch_perception(
            session_id,
            {
                "language": {
                    "latest_text": text,
                    "latest_function": "chat",
                    "latest_request_id": request_id,
                }
            },
        )
        return self.load(session_id, device_id=device_id)

    def apply_skill_result(
        self,
        session_id: str,
        result: Dict[str, Any],
        *,
        base_session: AgentSession | None = None,
    ) -> AgentSession:
        self._store.apply_agent_result(
            session_id,
            result,
            session_payload=None if base_session is None else base_session.session,
        )
        session = self.load(session_id)
        self.patch_perception(
            session_id,
            {
                "runtime": _runtime_result_snapshot(session.session),
                "language": _latest_language_snapshot(session.session),
            },
        )
        return self.load(session_id)

    def patch_latest_result(
        self,
        *,
        session_id: str,
        patch: Dict[str, Any],
        expected_request_id: Optional[str] = None,
        expected_frame_id: Optional[str] = None,
    ) -> AgentSession:
        self._store.patch_latest_result(
            session_id=session_id,
            patch=patch,
            expected_request_id=expected_request_id,
            expected_frame_id=expected_frame_id,
        )
        self.patch_perception(
            session_id,
            {"runtime": _runtime_result_snapshot(self.load(session_id).session)},
        )
        return self.load(session_id)

    def clear_turn_state(self, session_id: str) -> AgentSession:
        self._store.reset_session_context(session_id)
        self.patch_perception(
            session_id,
            {"runtime": _runtime_result_snapshot(self.load(session_id).session)},
        )
        return self.load(session_id)

    def patch_user_preferences(self, session_id: str, patch: Dict[str, Any]) -> AgentSession:
        self._ensure_session(session_id)
        self._store.patch_agent_state(session_id, user_preferences=patch)
        return self.load(session_id)

    def patch_environment(self, session_id: str, patch: Dict[str, Any]) -> AgentSession:
        self._ensure_session(session_id)
        self._store.patch_agent_state(session_id, environment_map=patch)
        return self.load(session_id)

    def patch_perception(self, session_id: str, patch: Dict[str, Any]) -> AgentSession:
        self._ensure_session(session_id)
        self._store.patch_agent_state(session_id, perception_cache=patch)
        return self.load(session_id)

    def patch_skill_state(
        self,
        session_id: str,
        *,
        skill_name: str,
        patch: Dict[str, Any],
    ) -> AgentSession:
        self._ensure_session(session_id)
        self._store.patch_agent_state(session_id, skill_cache={skill_name: patch})
        return self.load(session_id)
