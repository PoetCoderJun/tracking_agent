from __future__ import annotations

from typing import Any, Dict, Optional

from agent.session import AgentSession, AgentSessionStore
from capabilities.tracking.context import build_tracking_observation
from capabilities.tracking.effects import apply_tracking_decision, decision_from_select_output
from capabilities.tracking.select import execute_select_tool
from capabilities.tracking.types import TrackingDecision, TrackingObservation, TrackingTrigger


def _observation_context_payload(observation: TrackingObservation) -> Dict[str, Any]:
    return {
        "session_id": observation.session_id,
        "memory": observation.memory,
        "latest_target_id": observation.state.latest_target_id,
        "front_crop_path": observation.front_crop_path,
        "back_crop_path": observation.back_crop_path,
        "frames": list(observation.recent_frames),
    }


def Re(
    *,
    session: AgentSession,
    trigger: TrackingTrigger,
    excluded_track_ids: Optional[list[int]] = None,
) -> TrackingObservation:
    return build_tracking_observation(
        session,
        trigger=trigger,
        excluded_track_ids=excluded_track_ids,
    )


def Act(
    *,
    observation: TrackingObservation,
    env_file,
    artifacts_root,
) -> TrackingDecision:
    select_output = execute_select_tool(
        tracking_context=_observation_context_payload(observation),
        behavior="track",
        arguments={"user_text": observation.trigger.requested_text},
        env_file=env_file,
        artifacts_root=artifacts_root,
    )
    return decision_from_select_output(
        trigger=observation.trigger,
        select_output=select_output,
        target_description=observation.state.target_description,
    )


def run_tracking_agent_turn(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    session: AgentSession,
    trigger: TrackingTrigger,
    env_file,
    artifacts_root,
    excluded_track_ids: Optional[list[int]] = None,
) -> Dict[str, Any]:
    observation = Re(session=session, trigger=trigger, excluded_track_ids=excluded_track_ids)
    decision = Act(observation=observation, env_file=env_file, artifacts_root=artifacts_root)
    return apply_tracking_decision(
        sessions=sessions,
        session_id=session_id,
        session=session,
        trigger=trigger,
        decision=decision,
        env_file=env_file,
    )
