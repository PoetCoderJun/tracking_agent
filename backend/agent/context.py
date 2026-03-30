from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class AgentContext:
    session_id: str
    raw_session: Dict[str, Any]
    user_preferences: Dict[str, Any]
    environment_map: Dict[str, Any]
    perception_cache: Dict[str, Any]
    skill_cache: Dict[str, Any]
    state_paths: Dict[str, str]

    def merged_context(self) -> Dict[str, Any]:
        payload = dict(self.raw_session)
        payload["user_preferences"] = dict(self.user_preferences)
        payload["environment_map"] = dict(self.environment_map)
        payload["perception_cache"] = dict(self.perception_cache)
        payload["skill_cache"] = dict(self.skill_cache)
        payload["state_paths"] = dict(self.state_paths)
        return payload
