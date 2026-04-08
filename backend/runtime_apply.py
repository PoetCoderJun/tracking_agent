from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.runtime_session import AgentSession, AgentSessionStore

TRACKING_SKILL_NAME = "tracking"


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


def _schedule_rewrite_followup(
    *,
    skill_name: str,
    sessions: AgentSessionStore,
    session_id: str,
    rewrite_memory_input: Dict[str, Any],
    env_file: Path,
) -> None:
    if skill_name != TRACKING_SKILL_NAME:
        raise ValueError(f"rewrite_memory_input is not supported for skill: {skill_name}")

    from backend.tracking.deterministic import schedule_tracking_memory_rewrite

    schedule_tracking_memory_rewrite(
        sessions=sessions,
        session_id=session_id,
        rewrite_memory_input=rewrite_memory_input,
        env_file=env_file,
    )


def _maybe_run_sync_tracking_init_rewrite(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    env_file: Path,
    rewrite_output: Optional[Dict[str, Any]],
    rewrite_memory_input: Optional[Dict[str, Any]],
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if rewrite_output is not None:
        return rewrite_output, rewrite_memory_input
    if not isinstance(rewrite_memory_input, dict) or not rewrite_memory_input:
        return rewrite_output, rewrite_memory_input
    if str(rewrite_memory_input.get("task", "")).strip() != "init":
        return rewrite_output, rewrite_memory_input

    import backend.tracking.deterministic as tracking_orchestration_module

    session = sessions.load(session_id)
    resolved_rewrite_output = tracking_orchestration_module.execute_rewrite_memory_tool(
        session_file=Path(session.state_paths["session_path"]),
        arguments=dict(rewrite_memory_input),
        env_file=env_file,
    )
    tracking_orchestration_module.apply_tracking_rewrite_output(
        sessions=sessions,
        session_id=session_id,
        rewrite_output=resolved_rewrite_output,
    )
    return resolved_rewrite_output, None


def apply_processed_payload(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    pi_payload: Dict[str, Any],
    env_file: Path,
    base_session: AgentSession | None = None,
) -> Dict[str, Any]:
    skill_name = str(pi_payload.get("skill_name", "")).strip()
    if not skill_name:
        raise ValueError("Processed payload is missing skill_name")

    tool_output = _as_optional_dict(pi_payload.get("tool_output"), "tool_output")
    rewrite_output = _as_optional_dict(pi_payload.get("rewrite_output"), "rewrite_output")
    rewrite_memory_input = _as_optional_dict(pi_payload.get("rewrite_memory_input"), "rewrite_memory_input")
    session_result = _as_optional_dict(pi_payload.get("session_result"), "session_result")
    if session_result is None:
        raise ValueError("Processed payload is missing session_result")
    robot_response = _as_optional_dict(pi_payload.get("robot_response"), "robot_response")

    if skill_name == TRACKING_SKILL_NAME:
        rewrite_output, rewrite_memory_input = _maybe_run_sync_tracking_init_rewrite(
            sessions=sessions,
            session_id=session_id,
            env_file=env_file,
            rewrite_output=rewrite_output,
            rewrite_memory_input=rewrite_memory_input,
        )
        if rewrite_output and str(session_result.get("behavior", "")).strip() == "init":
            from backend.tracking.memory import tracking_memory_display_text

            memory_text = tracking_memory_display_text(rewrite_output.get("memory", {})).strip()
            if memory_text:
                session_result = dict(session_result)
                base_text = str(session_result.get("text", "")).strip()
                session_result["text"] = f"{base_text}\n{memory_text}".strip() if base_text else memory_text
                if robot_response is not None:
                    robot_response = dict(robot_response)
                    base_robot_text = str(robot_response.get("text", "")).strip()
                    robot_response["text"] = f"{base_robot_text}\n{memory_text}".strip() if base_robot_text else memory_text

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

    if (
        skill_name == TRACKING_SKILL_NAME
        and rewrite_output
        and str(session_result.get("behavior", "")).strip() == "init"
    ):
        import backend.tracking.deterministic as tracking_orchestration_module

        tracking_orchestration_module.apply_tracking_rewrite_output(
            sessions=sessions,
            session_id=session_id,
            rewrite_output=rewrite_output,
        )

    if rewrite_memory_input:
        _schedule_rewrite_followup(
            skill_name=skill_name,
            sessions=sessions,
            session_id=session_id,
            rewrite_memory_input=rewrite_memory_input,
            env_file=env_file,
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
