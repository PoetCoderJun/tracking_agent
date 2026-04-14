from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from agent.session import AgentSession, AgentSessionStore

TRACKING_SKILL_NAME = "tracking"
DEFAULT_PI_TURN_OWNER_ID = "pi"
STALE_TURN_REASON = "stale_request"


class _StaleOrdinaryTurn(RuntimeError):
    def __init__(self, *, latest_request_id: str, drop_stage: str) -> None:
        super().__init__(STALE_TURN_REASON)
        self.latest_request_id = latest_request_id
        self.drop_stage = drop_stage


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
    robot_response: Optional[Dict[str, Any]],
    tool: Any,
    tool_output: Optional[Dict[str, Any]],
    rewrite_output: Optional[Dict[str, Any]],
    rewrite_memory_input: Optional[Dict[str, Any]],
    latest_result: Dict[str, Any] | None,
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


def _resolved_turn_owner_id(turn_owner_id: str | None) -> str:
    return str(
        turn_owner_id
        or os.environ.get("ROBOT_AGENT_TURN_OWNER_ID")
        or DEFAULT_PI_TURN_OWNER_ID
    ).strip()


def _current_request_id(session: AgentSession) -> str:
    return str(session.session.get("latest_request_id") or "").strip()


def _assert_current_request(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    request_id: str,
    drop_stage: str,
) -> None:
    latest_request_id = _current_request_id(sessions.load(session_id))
    if latest_request_id and latest_request_id != request_id:
        raise _StaleOrdinaryTurn(
            latest_request_id=latest_request_id,
            drop_stage=drop_stage,
        )


def _dropped_skill_turn_payload(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    skill_name: str,
    request_id: str,
    latest_request_id: str,
    drop_stage: str,
) -> Dict[str, Any]:
    session = sessions.load(session_id)
    return {
        "session_id": session_id,
        "status": "dropped",
        "skill_name": skill_name,
        "request_id": request_id,
        "latest_request_id": latest_request_id,
        "reason": STALE_TURN_REASON,
        "drop_stage": drop_stage,
        "latest_result": session.latest_result,
        "session": session.session,
    }


def run_ordinary_skill_turn(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    skill_name: str,
    env_file: Path,
    build_payload: Callable[[AgentSession, str, Callable[[str], None]], Dict[str, Any]],
    request_id: str | None = None,
    turn_owner_id: str | None = None,
    turn_kind: str | None = None,
    wait_for_turn: bool = True,
) -> Dict[str, Any]:
    resolved_turn_owner_id = _resolved_turn_owner_id(turn_owner_id)
    resolved_turn_kind = str(turn_kind or f"pi:{skill_name}").strip()
    initial_session = sessions.load(session_id)
    bound_request_id = str(
        request_id
        or _current_request_id(initial_session)
        or f"{resolved_turn_kind}:{session_id}"
    ).strip()
    acquired = sessions.acquire_turn(
        session_id=session_id,
        owner_id=resolved_turn_owner_id,
        turn_kind=resolved_turn_kind,
        request_id=bound_request_id,
        wait=wait_for_turn,
    )
    if acquired is None:
        raise RuntimeError(
            f"Could not acquire runner turn lease for {resolved_turn_kind} on session {session_id}."
        )

    try:
        bound_session = sessions.load(session_id)
        try:
            _assert_current_request(
                sessions=sessions,
                session_id=session_id,
                request_id=bound_request_id,
                drop_stage="before_helper",
            )
        except _StaleOrdinaryTurn as exc:
            return _dropped_skill_turn_payload(
                sessions=sessions,
                session_id=session_id,
                skill_name=skill_name,
                request_id=bound_request_id,
                latest_request_id=exc.latest_request_id,
                drop_stage=exc.drop_stage,
            )

        def stale_guard(drop_stage: str) -> None:
            _assert_current_request(
                sessions=sessions,
                session_id=session_id,
                request_id=bound_request_id,
                drop_stage=drop_stage,
            )

        try:
            pi_payload = build_payload(bound_session, bound_request_id, stale_guard)
            stale_guard("before_commit")
        except _StaleOrdinaryTurn as exc:
            return _dropped_skill_turn_payload(
                sessions=sessions,
                session_id=session_id,
                skill_name=skill_name,
                request_id=bound_request_id,
                latest_request_id=exc.latest_request_id,
                drop_stage=exc.drop_stage,
            )
        return commit_skill_turn(
            sessions=sessions,
            session_id=session_id,
            pi_payload=pi_payload,
            env_file=env_file,
            turn_owner_id=resolved_turn_owner_id,
            turn_kind=resolved_turn_kind,
            acquire_turn=False,
        )
    finally:
        sessions.release_turn(
            session_id=session_id,
            owner_id=resolved_turn_owner_id,
            request_id=bound_request_id,
        )


def commit_skill_turn(
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
    resolved_turn_owner_id = _resolved_turn_owner_id(turn_owner_id)
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
            from capabilities.tracking.entrypoints.turns import apply_processed_tracking_payload

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


def run_due_tracking_step(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    device_id: str,
    env_file: Path,
    artifacts_root: Path,
    owner_id: str,
    continue_text: str = "继续跟踪",
    interval_seconds: float = 3.0,
) -> Dict[str, Any]:
    from capabilities.tracking.loop import supervisor_tracking_step

    return supervisor_tracking_step(
        sessions=sessions,
        session_id=session_id,
        device_id=device_id,
        env_file=env_file,
        artifacts_root=artifacts_root,
        owner_id=owner_id,
        continue_text=continue_text,
        interval_seconds=interval_seconds,
    )
