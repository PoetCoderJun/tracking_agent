from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class AgentSession:
    payload: Dict[str, Any]
    state_paths: Dict[str, str]

    @property
    def session_id(self) -> str:
        return str(self.payload["session_id"])

    @property
    def raw_session(self) -> Dict[str, Any]:
        return self.payload

    @property
    def session(self) -> Dict[str, Any]:
        return self.payload

    @property
    def user_preferences(self) -> Dict[str, Any]:
        return dict(self.payload.get("user_preferences", {}))

    @property
    def environment_map(self) -> Dict[str, Any]:
        return dict(self.payload.get("environment_map", {}))

    @property
    def environment(self) -> Dict[str, Any]:
        return self.environment_map

    @property
    def perception_cache(self) -> Dict[str, Any]:
        return dict(self.payload.get("perception_cache", {}))

    @property
    def perception(self) -> Dict[str, Any]:
        return self.perception_cache

    @property
    def skill_cache(self) -> Dict[str, Any]:
        return dict(self.payload.get("skill_cache", {}))

    @property
    def skills(self) -> Dict[str, Any]:
        return self.skill_cache

    @property
    def latest_result(self) -> Dict[str, Any] | None:
        latest_result = self.payload.get("latest_result")
        return None if not isinstance(latest_result, dict) else dict(latest_result)

    @property
    def conversation_history(self) -> List[Dict[str, Any]]:
        return list(self.payload.get("conversation_history", []))

    @property
    def recent_frames(self) -> List[Dict[str, Any]]:
        return list(self.payload.get("recent_frames", []))
