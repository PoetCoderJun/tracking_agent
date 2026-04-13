from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent.project_paths import resolve_project_path
from agent.session import AgentSession, AgentSessionStore
from agent.session_store import resolve_session_id
from agent.skill_payload import processed_skill_payload, reply_session_result
from capabilities.tracking.context import (
    TRACKING_LIFECYCLE_INACTIVE,
    TRACKING_LIFECYCLE_STOPPED,
    normalize_tracking_state,
)
from capabilities.tracking.effects import (
    PENDING_REWRITE_ENQUEUED_AT_KEY,
    PENDING_REWRITE_ERROR_KEY,
    PENDING_REWRITE_INPUT_KEY,
    PENDING_REWRITE_REQUEST_ID_KEY,
)
from capabilities.tracking.memory import reset_tracking_memory_snapshot

TRACKING_SKILL_NAME = "tracking"
TRACKING_STOP_SKILL_NAME = "tracking-stop"
DEFAULT_STATE_ROOT = "./.runtime/agent-runtime"


def _env_value(name: str) -> str:
    return str(os.environ.get(name, "")).strip()


def _resolved_state_root(raw_state_root: str | None) -> str:
    cleaned = str(raw_state_root or "").strip()
    if cleaned:
        return cleaned
    env_state_root = _env_value("ROBOT_AGENT_STATE_ROOT")
    if env_state_root:
        return env_state_root
    return DEFAULT_STATE_ROOT


def _resolved_session_id_arg(raw_session_id: str | None) -> str | None:
    cleaned = str(raw_session_id or "").strip()
    if cleaned:
        return cleaned
    env_session_id = _env_value("ROBOT_AGENT_SESSION_ID")
    if env_session_id:
        return env_session_id
    return None


def _is_tracking_active(session: AgentSession) -> bool:
    state = normalize_tracking_state(session.capabilities.get(TRACKING_SKILL_NAME))
    if state.latest_target_id is not None:
        return True
    if state.pending_question:
        return True
    return state.lifecycle_status not in ("", TRACKING_LIFECYCLE_INACTIVE, TRACKING_LIFECYCLE_STOPPED)


def _stop_tracking_state(*, sessions: AgentSessionStore, session_id: str) -> Dict[str, Any]:
    session = sessions.load(session_id)
    state = normalize_tracking_state(session.capabilities.get(TRACKING_SKILL_NAME))
    sessions.patch_skill_state(
        session_id,
        skill_name=TRACKING_SKILL_NAME,
        patch={
            "target_description": "",
            "latest_target_id": None,
            "pending_question": None,
            "lifecycle_status": TRACKING_LIFECYCLE_STOPPED,
            "next_tracking_turn_at": None,
            "stop_reason": "manual_stop",
            PENDING_REWRITE_INPUT_KEY: None,
            PENDING_REWRITE_REQUEST_ID_KEY: None,
            PENDING_REWRITE_ENQUEUED_AT_KEY: None,
            PENDING_REWRITE_ERROR_KEY: None,
        },
    )
    reset_tracking_memory_snapshot(
        state_root=sessions.state_root,
        session_id=session_id,
    )
    return {
        "was_active": True,
        "previous_target_id": state.latest_target_id,
        "previous_lifecycle_status": state.lifecycle_status,
        "stopped": True,
        "stop_reason": "manual_stop",
        "memory_reset": True,
    }


def _build_stop_payload(
    *,
    stopped: bool,
    tool_output: Dict[str, Any],
    request_id: str | None,
    request_function: str,
) -> Dict[str, Any]:
    text = "已停止跟踪当前目标。" if stopped else "当前没有进行中的跟踪。"
    session_result: Dict[str, Any] = {
        **reply_session_result(text, summary="tracking stop"),
        "function": request_function,
        "behavior": "stop",
    }
    if request_id not in (None, ""):
        session_result["request_id"] = str(request_id).strip()
    return processed_skill_payload(
        skill_name=TRACKING_STOP_SKILL_NAME,
        session_result=session_result,
        tool="stop",
        tool_output=tool_output,
    )


def run_stop_turn(
    *,
    session_id: str | None,
    state_root: Path,
    env_file: Path,
    bound_session: AgentSession | None = None,
    request_id: str | None = None,
    stale_guard: Callable[[str], None] | None = None,
) -> Dict[str, Any]:
    _ = env_file
    session = bound_session
    if session is None:
        resolved_session_id = resolve_session_id(
            state_root=state_root,
            session_id=session_id,
        )
        if resolved_session_id is None:
            raise ValueError("No active session found. Pass --session-id or create one first.")
        session = AgentSessionStore(state_root=state_root).load(resolved_session_id)

    request_function = str(session.session.get("latest_request_function") or "chat").strip() or "chat"
    if not _is_tracking_active(session):
        return _build_stop_payload(
            stopped=False,
            tool_output={"stopped": False, "reason": "idle"},
            request_id=request_id,
            request_function=request_function,
        )

    if stale_guard is not None:
        stale_guard("before_tracking_stop")

    tool_output = _stop_tracking_state(
        sessions=AgentSessionStore(state_root=state_root),
        session_id=session.session_id,
    )
    return _build_stop_payload(
        stopped=True,
        tool_output=tool_output,
        request_id=request_id,
        request_function=request_function,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic tracking stop skill turn.")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--state-root", default=None)
    parser.add_argument("--env-file", default=".ENV")
    args = parser.parse_args(argv)

    payload = run_stop_turn(
        session_id=_resolved_session_id_arg(args.session_id),
        state_root=resolve_project_path(_resolved_state_root(args.state_root)),
        env_file=resolve_project_path(args.env_file),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
