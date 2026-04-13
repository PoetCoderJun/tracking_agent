from __future__ import annotations

from dataclasses import dataclass
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.session_store import ActiveSessionStore, LiveSessionStore


def _refresh_viewer_snapshot(*, state_root: Path, session_id: str | None = None) -> None:
    from interfaces.viewer.stream import write_agent_viewer_snapshot

    write_agent_viewer_snapshot(state_root=state_root, session_id=session_id)


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


def _latest_user_text(session: Dict[str, Any]) -> str:
    history = session.get("conversation_history") or []
    for entry in reversed(history):
        if str(entry.get("role", "")).strip() != "user":
            continue
        text = str(entry.get("text", "")).strip()
        if text:
            return text
    return ""


def _recent_dialogue(session: Dict[str, Any], *, limit: int) -> List[Dict[str, Any]]:
    normalized_limit = max(0, int(limit))
    if normalized_limit == 0:
        return []
    return [
        {
            "role": str(entry.get("role", "")).strip(),
            "text": str(entry.get("text", "")).strip(),
            "timestamp": str(entry.get("timestamp", "")).strip(),
        }
        for entry in list(session.get("conversation_history") or [])[-normalized_limit:]
        if isinstance(entry, dict)
    ]


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


@dataclass(frozen=True)
class AgentSession:
    payload: Dict[str, Any]
    state_paths: Dict[str, str]

    @property
    def session_id(self) -> str:
        return str(self.payload["session_id"])

    @property
    def session(self) -> Dict[str, Any]:
        return self.payload

    @property
    def state(self) -> Dict[str, Any]:
        return dict(self.payload.get("state") or {})

    @property
    def user_preferences(self) -> Dict[str, Any]:
        return dict(self.state.get("user_preferences", {}))

    @property
    def environment_map(self) -> Dict[str, Any]:
        return dict(self.state.get("environment", {}))

    @property
    def environment(self) -> Dict[str, Any]:
        return self.environment_map

    @property
    def perception(self) -> Dict[str, Any]:
        return {
            "language": self.language_context,
            "runtime": _runtime_result_snapshot(self.payload),
        }

    @property
    def runner_state(self) -> Dict[str, Any]:
        return dict(self.state.get("runner", {}))

    @property
    def capabilities(self) -> Dict[str, Any]:
        return dict(self.state.get("capabilities", {}))

    @property
    def latest_result(self) -> Dict[str, Any] | None:
        latest_result = self.payload.get("latest_result")
        return None if not isinstance(latest_result, dict) else dict(latest_result)

    @property
    def conversation_history(self) -> List[Dict[str, Any]]:
        return list(self.payload.get("conversation_history", []))

    @property
    def latest_user_text(self) -> str:
        return _latest_user_text(self.payload)

    @property
    def language_context(self) -> Dict[str, Any]:
        snapshot = _latest_language_snapshot(self.payload)
        return {
            **snapshot,
            "latest_user_text": self.latest_user_text,
            "recent_dialogue": _recent_dialogue(self.payload, limit=6),
        }

    def recent_dialogue(self, *, limit: int = 6) -> List[Dict[str, Any]]:
        return _recent_dialogue(self.payload, limit=limit)

    @property
    def runtime_summary(self) -> Dict[str, Any]:
        return _runtime_result_snapshot(self.payload)

    @property
    def perception_snapshot(self) -> Dict[str, Any]:
        from world.perception.service import LocalPerceptionService

        return LocalPerceptionService(Path(self.state_paths["state_root"])).read_snapshot()

class AgentSessionStore:
    def __init__(self, state_root: Path):
        self._state_root = state_root
        self._store = LiveSessionStore(state_root=state_root)

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
        _refresh_viewer_snapshot(state_root=self._state_root, session_id=session_id)
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
        _refresh_viewer_snapshot(state_root=self._state_root, session_id=session_id)
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
        _refresh_viewer_snapshot(state_root=self._state_root, session_id=session_id)
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
        _refresh_viewer_snapshot(state_root=self._state_root, session_id=session_id)
        return self.load(session_id)

    def clear_turn_state(self, session_id: str) -> AgentSession:
        self._store.reset_session_context(session_id)
        _refresh_viewer_snapshot(state_root=self._state_root, session_id=session_id)
        return self.load(session_id)

    def patch_user_preferences(self, session_id: str, patch: Dict[str, Any]) -> AgentSession:
        self._ensure_session(session_id)
        self._store.patch_agent_state(session_id, user_preferences=patch)
        _refresh_viewer_snapshot(state_root=self._state_root, session_id=session_id)
        return self.load(session_id)

    def patch_environment(self, session_id: str, patch: Dict[str, Any]) -> AgentSession:
        self._ensure_session(session_id)
        self._store.patch_agent_state(session_id, environment_map=patch)
        _refresh_viewer_snapshot(state_root=self._state_root, session_id=session_id)
        return self.load(session_id)

    def patch_runner_state(self, session_id: str, patch: Dict[str, Any]) -> AgentSession:
        self._ensure_session(session_id)
        self._store.patch_agent_state(session_id, runner_state=patch)
        _refresh_viewer_snapshot(state_root=self._state_root, session_id=session_id)
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
        _refresh_viewer_snapshot(state_root=self._state_root, session_id=session_id)
        return self.load(session_id)

    def acquire_turn(
        self,
        *,
        session_id: str,
        owner_id: str,
        turn_kind: str,
        request_id: str,
        device_id: str = "",
        wait: bool = False,
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.05,
        stale_after_seconds: float = 30.0,
    ) -> AgentSession | None:
        deadline = time.time() + max(0.0, timeout_seconds)
        while True:
            acquired = self._store.try_acquire_turn(
                session_id=session_id,
                owner_id=owner_id,
                turn_kind=turn_kind,
                request_id=request_id,
                device_id=device_id,
                stale_after_seconds=stale_after_seconds,
            )
            if acquired is not None:
                return self.load(session_id, device_id=device_id)
            if not wait or time.time() >= deadline:
                return None
            time.sleep(max(0.01, poll_interval_seconds))

    def release_turn(
        self,
        *,
        session_id: str,
        owner_id: str,
        request_id: str | None = None,
        device_id: str = "",
    ) -> AgentSession:
        self._store.release_turn(
            session_id=session_id,
            owner_id=owner_id,
            request_id=request_id,
            device_id=device_id,
        )
        return self.load(session_id, device_id=device_id)


def bootstrap_runner_session(
    *,
    state_root: Path,
    device_id: str = "robot_01",
    session_id: str | None = None,
    fresh: bool = False,
) -> AgentSession:
    from world.perception.stream import generate_session_id

    sessions = AgentSessionStore(state_root=state_root)
    requested_session_id = str(session_id or "").strip()
    resolved_session_id = requested_session_id or generate_session_id(prefix="runtime")
    session = (
        sessions.start_fresh_session(resolved_session_id, device_id=device_id)
        if fresh
        else sessions.load(resolved_session_id, device_id=device_id)
    )
    ActiveSessionStore(state_root).write(resolved_session_id)
    _refresh_viewer_snapshot(state_root=state_root, session_id=resolved_session_id)
    return session
