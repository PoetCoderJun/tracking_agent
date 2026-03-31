from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.agent.context import AgentContext
from backend.agent.context_views import build_route_context, build_tracking_context


@dataclass(frozen=True)
class RouteContextBuilder:
    def build(
        self,
        context: AgentContext,
        *,
        request_id: str,
        enabled_skill_names: List[str],
    ) -> Dict[str, Any]:
        return build_route_context(
            context,
            request_id=request_id,
            enabled_skill_names=enabled_skill_names,
        )


@dataclass(frozen=True)
class TrackingContextBuilder:
    def build(
        self,
        context: AgentContext,
        *,
        request_id: str,
        recovery_mode: bool = False,
        missing_target_id: Optional[int] = None,
        candidate_track_id_floor_exclusive: Optional[int] = None,
    ) -> Dict[str, Any]:
        return build_tracking_context(
            context,
            request_id=request_id,
            recovery_mode=recovery_mode,
            missing_target_id=missing_target_id,
            candidate_track_id_floor_exclusive=candidate_track_id_floor_exclusive,
        )
