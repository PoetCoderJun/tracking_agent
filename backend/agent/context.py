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
