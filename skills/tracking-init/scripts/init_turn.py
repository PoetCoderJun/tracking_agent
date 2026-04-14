from __future__ import annotations

import argparse
import json
import os
from typing import List, Optional

from world.perception.stream import generate_request_id
from agent.session_store import resolve_session_id
from agent.project_paths import resolve_project_path
from agent.session import AgentSessionStore
from capabilities.tracking.entrypoints.turns import process_tracking_init_direct

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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic tracking-init skill turn.")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--text", required=True)
    parser.add_argument("--device-id", default="robot_01")
    parser.add_argument("--state-root", default=None)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    parser.add_argument("--request-id", default=None)
    args = parser.parse_args(argv)

    state_root = resolve_project_path(_resolved_state_root(args.state_root))
    session_id = resolve_session_id(
        state_root=state_root,
        session_id=_resolved_session_id_arg(args.session_id),
    )
    if session_id is None:
        raise ValueError("No active session found. Pass --session-id or create one first.")

    sessions = AgentSessionStore(state_root=state_root)
    payload = process_tracking_init_direct(
        sessions=sessions,
        session_id=session_id,
        device_id=args.device_id,
        text=str(args.text),
        request_id=args.request_id or generate_request_id(prefix="init"),
        env_file=resolve_project_path(args.env_file),
        artifacts_root=resolve_project_path(args.artifacts_root),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
