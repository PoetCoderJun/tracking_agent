from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from backend.persistence import LiveSessionStore


@dataclass(frozen=True)
class AgentMemoryRecord:
    session_id: str
    user_preferences: Dict[str, Any]
    environment_map: Dict[str, Any]
    perception_cache: Dict[str, Any]
    skill_cache: Dict[str, Any]
    updated_at: str


class AgentMemoryStore:
    """Compatibility view over the agent-owned sections now stored in session.json."""

    def __init__(self, state_root: Path, session_id: str):
        self._state_root = state_root
        self._session_id = session_id
        self._store = LiveSessionStore(state_root=state_root)

    def session_dir(self) -> Path:
        path = self._state_root / "sessions" / self._session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path(self) -> Path:
        return self.session_dir() / "session.json"

    def load(self) -> AgentMemoryRecord:
        payload = self._store.session_payload(self._session_id)
        return AgentMemoryRecord(
            session_id=str(payload["session_id"]),
            user_preferences=dict(payload.get("user_preferences", {})),
            environment_map=dict(payload.get("environment_map", {})),
            perception_cache=dict(payload.get("perception_cache", {})),
            skill_cache=dict(payload.get("skill_cache", {})),
            updated_at=str(payload["updated_at"]),
        )

    def load_if_exists(self) -> Optional[AgentMemoryRecord]:
        path = self.path()
        if not path.exists():
            return None
        return self.load()

    def load_or_create(self) -> AgentMemoryRecord:
        existing = self.load_if_exists()
        if existing is not None:
            return existing
        record = self.reset()
        return record

    def reset(self) -> AgentMemoryRecord:
        self._store.reset_agent_state(self._session_id)
        return self.load()

    def write(self, record: AgentMemoryRecord) -> AgentMemoryRecord:
        self._store.replace_agent_state(
            self._session_id,
            user_preferences=record.user_preferences,
            environment_map=record.environment_map,
            perception_cache=record.perception_cache,
            skill_cache=record.skill_cache,
        )
        return self.load()

    def update_user_preferences(self, preferences: Dict[str, Any]) -> AgentMemoryRecord:
        self._store.patch_agent_state(self._session_id, user_preferences=dict(preferences))
        return self.load()

    def update_environment_map(self, environment_map: Dict[str, Any]) -> AgentMemoryRecord:
        self._store.patch_agent_state(self._session_id, environment_map=dict(environment_map))
        return self.load()

    def update_perception_cache(self, patch: Dict[str, Any]) -> AgentMemoryRecord:
        self._store.patch_agent_state(self._session_id, perception_cache=dict(patch))
        return self.load()

    def update_skill_cache(self, skill_name: str, patch: Dict[str, Any]) -> AgentMemoryRecord:
        if not skill_name.strip():
            raise ValueError("skill_name must not be empty")
        self._store.patch_agent_state(self._session_id, skill_cache={skill_name: dict(patch)})
        return self.load()
