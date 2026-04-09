from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from backend.runtime_session import AgentSession, AgentSessionStore

TRACKING_SKILL_NAME = "tracking"
DEFAULT_PI_TURN_OWNER_ID = "pi"


def _as_optional_dict(value: Any, field_name: str) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object or null")
    return dict(value)


def _normalize_skill_state_patch(skill_name: str, patch: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if patch is None:
        return None
    nested = patch.get(skill_name)
    if len(patch) == 1 and isinstance(nested, dict):
        return dict(nested)
    return patch


def _compact_response_payload(
    *,
    session_id: str,
    skill_name: str,
    session_result: Dict[str, Any],
    latest_result_patch: Optional[Dict[str, Any]],
    skill_state_patch: Optional[Dict[str, Any]],
    user_preferences_patch: Optional[Dict[str, Any]],
    environment_map_patch: Optional[Dict[str, Any]],
    perception_cache_patch: Optional[Dict[str, Any]],
    robot_response: Optional[Dict[str, Any]],
    tool: Any,
    tool_output: Optional[Dict[str, Any]],
    rewrite_output: Optional[Dict[str, Any]],
    rewrite_memory_input: Optional[Dict[str, Any]],
    latest_result: Dict[str, Any],
    session: Dict[str, Any],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "status": "processed",
        "skill_name": skill_name,
        "session_result": session_result,
        "tool": tool,
        "latest_result": latest_result,
        "session": session,
    }
    optional_fields = {
        "latest_result_patch": latest_result_patch,
        "skill_state_patch": skill_state_patch,
        "user_preferences_patch": user_preferences_patch,
        "environment_map_patch": environment_map_patch,
        "perception_cache_patch": perception_cache_patch,
        "robot_response": robot_response,
        "tool_output": tool_output,
        "rewrite_output": rewrite_output,
        "rewrite_memory_input": rewrite_memory_input,
    }
    for key, value in optional_fields.items():
        if isinstance(value, dict):
            if value:
                payload[key] = value
            continue
        if value is not None:
            payload[key] = value
    return payload


def apply_processed_payload(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    pi_payload: Dict[str, Any],
    env_file: Path,
    base_session: AgentSession | None = None,
    turn_owner_id: str | None = None,
    turn_kind: str | None = None,
    acquire_turn: bool = True,
) -> Dict[str, Any]:
    skill_name = str(pi_payload.get("skill_name", "")).strip()
    if not skill_name:
        raise ValueError("Processed payload is missing skill_name")

    session_result = _as_optional_dict(pi_payload.get("session_result"), "session_result")
    if session_result is None:
        raise ValueError("Processed payload is missing session_result")
    resolved_turn_owner_id = str(
        turn_owner_id
        or os.environ.get("ROBOT_AGENT_TURN_OWNER_ID")
        or DEFAULT_PI_TURN_OWNER_ID
    ).strip()
    resolved_turn_kind = str(turn_kind or f"pi:{skill_name}").strip()
    initial_session = sessions.load(session_id)
    turn_request_id = str(
        session_result.get("request_id")
        or initial_session.session.get("latest_request_id")
        or f"{resolved_turn_kind}:{session_id}"
    ).strip()

    if acquire_turn:
        acquired = sessions.acquire_turn(
            session_id=session_id,
            owner_id=resolved_turn_owner_id,
            turn_kind=resolved_turn_kind,
            request_id=turn_request_id,
            wait=True,
        )
        if acquired is None:
            raise RuntimeError(
                f"Could not acquire runner turn lease for {resolved_turn_kind} on session {session_id}."
            )

    try:
        if skill_name == TRACKING_SKILL_NAME:
            from backend.tracking.deterministic import apply_processed_tracking_payload

            return apply_processed_tracking_payload(
                sessions=sessions,
                session_id=session_id,
                pi_payload=pi_payload,
                env_file=env_file,
            )

        tool_output = _as_optional_dict(pi_payload.get("tool_output"), "tool_output")
        rewrite_output = _as_optional_dict(pi_payload.get("rewrite_output"), "rewrite_output")
        rewrite_memory_input = _as_optional_dict(pi_payload.get("rewrite_memory_input"), "rewrite_memory_input")
        robot_response = _as_optional_dict(pi_payload.get("robot_response"), "robot_response")
        sessions.apply_skill_result(
            session_id,
            session_result,
            base_session=base_session,
        )

        latest_result_patch = _as_optional_dict(pi_payload.get("latest_result_patch"), "latest_result_patch")
        if latest_result_patch:
            sessions.patch_latest_result(
                session_id=session_id,
                patch=latest_result_patch,
                expected_request_id=session_result.get("request_id"),
                expected_frame_id=session_result.get("frame_id"),
            )

        user_preferences_patch = _as_optional_dict(pi_payload.get("user_preferences_patch"), "user_preferences_patch")
        if user_preferences_patch:
            sessions.patch_user_preferences(session_id, user_preferences_patch)

        environment_map_patch = _as_optional_dict(pi_payload.get("environment_map_patch"), "environment_map_patch")
        if environment_map_patch:
            sessions.patch_environment(session_id, environment_map_patch)

        perception_cache_patch = _as_optional_dict(pi_payload.get("perception_cache_patch"), "perception_cache_patch")
        if perception_cache_patch:
            sessions.patch_perception(session_id, perception_cache_patch)

        skill_state_patch = _normalize_skill_state_patch(
            skill_name,
            _as_optional_dict(pi_payload.get("skill_state_patch"), "skill_state_patch"),
        )
        if skill_state_patch:
            sessions.patch_skill_state(
                session_id,
                skill_name=skill_name,
                patch=skill_state_patch,
            )

        final_session = sessions.load(session_id)
        return _compact_response_payload(
            session_id=session_id,
            skill_name=skill_name,
            session_result=session_result,
            latest_result_patch=latest_result_patch,
            skill_state_patch=skill_state_patch,
            user_preferences_patch=user_preferences_patch,
            environment_map_patch=environment_map_patch,
            perception_cache_patch=perception_cache_patch,
            robot_response=robot_response or session_result.get("robot_response"),
            tool=pi_payload.get("tool"),
            tool_output=tool_output,
            rewrite_output=rewrite_output,
            rewrite_memory_input=rewrite_memory_input,
            latest_result=final_session.latest_result,
            session=final_session.session,
        )
    finally:
        if acquire_turn:
            sessions.release_turn(
                session_id=session_id,
                owner_id=resolved_turn_owner_id,
                request_id=turn_request_id,
            )
