from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from agent.infra.paths import resolve_project_path
from agent.state.active import resolve_session_id
from agent.state.session import AgentSessionStore
from capabilities.tracking.agent import run_tracking_agent_turn
from capabilities.tracking.runtime.effects import (
    drain_pending_tracking_memory_rewrite,
    pending_tracking_memory_rewrite,
)
from capabilities.tracking.runtime.triggers import derive_continuous_trigger, tracking_runtime_status

DEFAULT_SUPERVISOR_POLL_SECONDS = 0.25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tracking debug adapter. Runs one supervisor-style tracking step against the current session."
    )
    parser.add_argument("--session-id", default=None, help="Optional. If omitted, follows the current active session.")
    parser.add_argument("--device-id", default="robot_01")
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    parser.add_argument("--continue-text", default="继续跟踪")
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--stop-file", default=None)
    return parser.parse_args()


def _sessions_from_args(args: argparse.Namespace) -> AgentSessionStore:
    return AgentSessionStore(state_root=resolve_project_path(args.state_root))


def supervisor_tracking_step(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    device_id: str,
    env_file: Path,
    artifacts_root: Path,
    owner_id: str,
    continue_text: str = "继续跟踪",
) -> Dict[str, Any]:
    session = sessions.load(session_id, device_id=device_id)
    pending_rewrite = pending_tracking_memory_rewrite(session)
    if pending_rewrite is not None:
        rewrite_request_id = str(pending_rewrite.get("request_id", "") or f"rewrite:{session_id}").strip()
        acquired = sessions.acquire_turn(
            session_id=session_id,
            owner_id=owner_id,
            turn_kind="tracking-init-rewrite",
            request_id=rewrite_request_id,
            device_id=device_id,
            wait=False,
        )
        if acquired is None:
            return {"status": "busy", "reason": "lease_held", "sleep_seconds": DEFAULT_SUPERVISOR_POLL_SECONDS}
        try:
            rewrite_payload = drain_pending_tracking_memory_rewrite(
                sessions=sessions,
                session_id=session_id,
                env_file=env_file,
            )
        finally:
            sessions.release_turn(
                session_id=session_id,
                owner_id=owner_id,
                request_id=rewrite_request_id,
                device_id=device_id,
            )
        return {
            "status": f"rewrite_{rewrite_payload.get('status', 'idle')}",
            "request_id": rewrite_request_id,
            "trigger": "background_rewrite",
            "cause": "pending_rewrite",
            "payload": rewrite_payload,
            "sleep_seconds": DEFAULT_SUPERVISOR_POLL_SECONDS,
        }

    runtime_status = tracking_runtime_status(session)
    trigger = derive_continuous_trigger(session)
    if trigger is None:
        return {
            "status": runtime_status["status"],
            "target_present": runtime_status.get("target_present", False),
            "sleep_seconds": DEFAULT_SUPERVISOR_POLL_SECONDS,
        }

    acquired = sessions.acquire_turn(
        session_id=session_id,
        owner_id=owner_id,
        turn_kind="tracking-init-runtime",
        request_id=trigger.request_id,
        device_id=device_id,
        wait=False,
    )
    if acquired is None:
        return {"status": "busy", "reason": "lease_held", "sleep_seconds": DEFAULT_SUPERVISOR_POLL_SECONDS}

    try:
        payload = run_tracking_agent_turn(
            sessions=sessions,
            session_id=session_id,
            session=sessions.load(session_id, device_id=device_id),
            trigger=trigger,
            env_file=env_file,
            artifacts_root=artifacts_root,
        )
    finally:
        sessions.release_turn(
            session_id=session_id,
            owner_id=owner_id,
            request_id=trigger.request_id,
            device_id=device_id,
        )

    result = dict(payload.get("session_result") or {})
    return {
        "status": "tracked" if bool(result.get("found", False)) else "waiting",
        "request_id": trigger.request_id,
        "trigger": trigger.type,
        "cause": trigger.cause,
        "payload": payload,
        "sleep_seconds": DEFAULT_SUPERVISOR_POLL_SECONDS,
    }


def main() -> int:
    args = parse_args()
    sessions = _sessions_from_args(args)
    env_file = resolve_project_path(args.env_file)
    artifacts_root = resolve_project_path(args.artifacts_root)
    session_id = resolve_session_id(
        state_root=resolve_project_path(args.state_root),
        session_id=args.session_id,
    )
    if session_id is None:
        print(json.dumps({"session_id": None, "status": "idle", "reason": "No active session."}, ensure_ascii=True), flush=True)
        return 0

    payload = supervisor_tracking_step(
        sessions=sessions,
        session_id=session_id,
        device_id=args.device_id,
        env_file=env_file,
        artifacts_root=artifacts_root,
        owner_id=f"tracking-loop-debug:{session_id}",
        continue_text=args.continue_text,
    )
    print(json.dumps(payload, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
