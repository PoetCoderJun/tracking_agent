from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping

from agent.config import parse_dotenv
from agent.session_store import resolve_session_id
from agent.project_paths import resolve_project_path
from agent.session import AgentSessionStore
from capabilities.tracking.agent import run_tracking_agent_turn
from capabilities.tracking.effects import drain_pending_tracking_memory_rewrite, pending_tracking_memory_rewrite
from capabilities.tracking.triggers import derive_continuous_trigger, tracking_runtime_status

DEFAULT_SUPERVISOR_POLL_SECONDS = 0.25


def _load_tracking_env_values(env_file: str | Path) -> dict[str, str]:
    return parse_dotenv(resolve_project_path(env_file))


def _float_env_value(values: Mapping[str, str], key: str, default: float) -> float:
    raw = str(values.get(key, "")).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def parse_args() -> argparse.Namespace:
    bootstrap_parser = argparse.ArgumentParser(add_help=False)
    bootstrap_parser.add_argument("--env-file", default=".ENV")
    bootstrap_args, _ = bootstrap_parser.parse_known_args()
    env_values = _load_tracking_env_values(bootstrap_args.env_file)

    parser = argparse.ArgumentParser(
        description="Tracking debug adapter. Runs one supervisor-style tracking step against the current session."
    )
    parser.add_argument("--session-id", default=None, help="Optional. If omitted, follows the current active session.")
    parser.add_argument("--device-id", default="robot_01")
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--env-file", default=bootstrap_args.env_file)
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    parser.add_argument("--continue-text", default="继续跟踪")
    parser.add_argument("--interval-seconds", type=float, default=_float_env_value(env_values, "QUERY_INTERVAL_SECONDS", 3.0))
    parser.add_argument("--recovery-interval-seconds", type=float, default=_float_env_value(env_values, "TRACKING_RECOVERY_INTERVAL_SECONDS", 1.0))
    parser.add_argument("--idle-sleep-seconds", type=float, default=_float_env_value(env_values, "TRACKING_IDLE_SLEEP_SECONDS", 3.0))
    parser.add_argument("--presence-check-seconds", type=float, default=_float_env_value(env_values, "TRACKING_PRESENCE_CHECK_SECONDS", 1.0))
    parser.add_argument("--rewrite-interval-seconds", type=float, default=_float_env_value(env_values, "TRACKING_MEMORY_REWRITE_INTERVAL_SECONDS", 2.0))
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
    interval_seconds: float = 3.0,
) -> Dict[str, Any]:
    session = sessions.load(session_id, device_id=device_id)
    pending_rewrite = pending_tracking_memory_rewrite(session)
    if pending_rewrite is not None:
        rewrite_request_id = str(pending_rewrite.get("request_id", "") or f"rewrite:{session_id}").strip()
        acquired = sessions.acquire_turn(
            session_id=session_id,
            owner_id=owner_id,
            turn_kind="tracking-rewrite",
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
        turn_kind="tracking",
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
        "sleep_seconds": DEFAULT_SUPERVISOR_POLL_SECONDS if interval_seconds > 0 else DEFAULT_SUPERVISOR_POLL_SECONDS,
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
        interval_seconds=args.interval_seconds,
    )
    print(json.dumps(payload, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
