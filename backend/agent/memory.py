from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_nested(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(dict(merged[key]), value)
            continue
        merged[key] = value
    return merged


@dataclass(frozen=True)
class AgentMemoryRecord:
    session_id: str
    user_preferences: Dict[str, Any]
    environment_map: Dict[str, Any]
    perception_cache: Dict[str, Any]
    skill_cache: Dict[str, Any]
    updated_at: str


class AgentMemoryStore:
    def __init__(self, state_root: Path, session_id: str):
        self._state_root = state_root
        self._session_id = session_id

    def session_dir(self) -> Path:
        path = self._state_root / "sessions" / self._session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path(self) -> Path:
        return self.session_dir() / "agent_memory.json"

    def load(self) -> AgentMemoryRecord:
        payload = json.loads(self.path().read_text(encoding="utf-8"))
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
        record = AgentMemoryRecord(
            session_id=self._session_id,
            user_preferences={},
            environment_map={},
            perception_cache={},
            skill_cache={},
            updated_at=_utc_now(),
        )
        self.write(record)
        return record

    def write(self, record: AgentMemoryRecord) -> AgentMemoryRecord:
        self.path().write_text(
            json.dumps(asdict(record), indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        return record

    def update_user_preferences(self, preferences: Dict[str, Any]) -> AgentMemoryRecord:
        record = self.load_or_create()
        return self.write(
            AgentMemoryRecord(
                session_id=record.session_id,
                user_preferences=_merge_nested(record.user_preferences, dict(preferences)),
                environment_map=record.environment_map,
                perception_cache=record.perception_cache,
                skill_cache=record.skill_cache,
                updated_at=_utc_now(),
            )
        )

    def update_environment_map(self, environment_map: Dict[str, Any]) -> AgentMemoryRecord:
        record = self.load_or_create()
        return self.write(
            AgentMemoryRecord(
                session_id=record.session_id,
                user_preferences=record.user_preferences,
                environment_map=_merge_nested(record.environment_map, dict(environment_map)),
                perception_cache=record.perception_cache,
                skill_cache=record.skill_cache,
                updated_at=_utc_now(),
            )
        )

    def update_perception_cache(self, patch: Dict[str, Any]) -> AgentMemoryRecord:
        record = self.load_or_create()
        return self.write(
            AgentMemoryRecord(
                session_id=record.session_id,
                user_preferences=record.user_preferences,
                environment_map=record.environment_map,
                perception_cache=_merge_nested(record.perception_cache, dict(patch)),
                skill_cache=record.skill_cache,
                updated_at=_utc_now(),
            )
        )

    def update_skill_cache(self, skill_name: str, patch: Dict[str, Any]) -> AgentMemoryRecord:
        if not skill_name.strip():
            raise ValueError("skill_name must not be empty")
        record = self.load_or_create()
        skill_cache = dict(record.skill_cache)
        existing = dict(skill_cache.get(skill_name, {}))
        skill_cache[skill_name] = _merge_nested(existing, dict(patch))
        return self.write(
            AgentMemoryRecord(
                session_id=record.session_id,
                user_preferences=record.user_preferences,
                environment_map=record.environment_map,
                perception_cache=record.perception_cache,
                skill_cache=skill_cache,
                updated_at=_utc_now(),
            )
        )
