#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from world.perception.stream import generate_request_id
from agent.session_store import resolve_session_id
from agent.project_paths import resolve_project_path
from agent.session import AgentSessionStore, bootstrap_runner_session
from capabilities.tracking.deterministic import (
    process_tracking_init_direct,
    process_tracking_request_direct,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Runtime utility CLI for sessions and deterministic tracking checks."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    runner_bootstrap = subparsers.add_parser(
        "runner-bootstrap",
        help="Create or attach the unique active session owned by the main runner.",
    )
    runner_bootstrap.add_argument("--session-id", default=None)
    runner_bootstrap.add_argument("--device-id", default="robot_01")
    runner_bootstrap.add_argument("--state-root", default="./.runtime/agent-runtime")
    runner_bootstrap.add_argument("--fresh", action="store_true")

    session_show = subparsers.add_parser(
        "session-show",
        help="Read the persisted runtime session payload and state paths.",
    )
    session_show.add_argument("--session-id", default=None)
    session_show.add_argument("--device-id", default="robot_01")
    session_show.add_argument("--state-root", default="./.runtime/agent-runtime")

    tracking_track = subparsers.add_parser(
        "tracking-track",
        help="Run one deterministic backend tracking step against the current session state.",
    )
    tracking_track.add_argument("--session-id", default=None)
    tracking_track.add_argument("--text", default="继续跟踪")
    tracking_track.add_argument("--device-id", default="robot_01")
    tracking_track.add_argument("--state-root", default="./.runtime/agent-runtime")
    tracking_track.add_argument("--env-file", default=".ENV")
    tracking_track.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    tracking_track.add_argument("--request-id", default=None)

    tracking_init = subparsers.add_parser(
        "tracking-init",
        help="Run one deterministic backend init step against the current session state.",
    )
    tracking_init.add_argument("--session-id", default=None)
    tracking_init.add_argument("--text", required=True)
    tracking_init.add_argument("--device-id", default="robot_01")
    tracking_init.add_argument("--state-root", default="./.runtime/agent-runtime")
    tracking_init.add_argument("--env-file", default=".ENV")
    tracking_init.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    tracking_init.add_argument("--request-id", default=None)

    return parser.parse_args()


def _session_store_from_args(args: argparse.Namespace) -> AgentSessionStore:
    return AgentSessionStore(state_root=resolve_project_path(args.state_root))


def _resolved_active_or_explicit_session_id(args: argparse.Namespace) -> str:
    session_id = resolve_session_id(
        state_root=resolve_project_path(args.state_root),
        session_id=args.session_id,
    )
    if session_id is None:
        raise ValueError("No active session found. Pass --session-id or bootstrap one first with runner-bootstrap.")
    return session_id


def _session_payload(session) -> dict:
    return {
        "session_id": session.session_id,
        "state_paths": dict(session.state_paths),
        "session": session.session,
    }


def main() -> int:
    args = parse_args()

    if args.command == "runner-bootstrap":
        state_root = resolve_project_path(args.state_root)
        session = bootstrap_runner_session(
            state_root=state_root,
            device_id=args.device_id,
            session_id=args.session_id,
            fresh=bool(args.fresh),
        )
        print(
            json.dumps(
                {
                    "status": "bootstrapped",
                    "session_id": session.session_id,
                    "device_id": session.session.get("device_id") or args.device_id,
                    "state_paths": dict(session.state_paths),
                    "session": session.session,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "session-show":
        sessions = _session_store_from_args(args)
        session_id = _resolved_active_or_explicit_session_id(args)
        session = sessions.load(session_id, device_id=args.device_id)
        print(json.dumps(_session_payload(session), ensure_ascii=False))
        return 0

    if args.command == "tracking-track":
        sessions = _session_store_from_args(args)
        session_id = _resolved_active_or_explicit_session_id(args)
        payload = process_tracking_request_direct(
            sessions=sessions,
            session_id=session_id,
            device_id=args.device_id,
            text=args.text,
            request_id=args.request_id or generate_request_id(prefix="track"),
            env_file=resolve_project_path(args.env_file),
            artifacts_root=resolve_project_path(args.artifacts_root),
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "tracking-init":
        sessions = _session_store_from_args(args)
        session_id = _resolved_active_or_explicit_session_id(args)
        payload = process_tracking_init_direct(
            sessions=sessions,
            session_id=session_id,
            device_id=args.device_id,
            text=args.text,
            request_id=args.request_id or generate_request_id(prefix="init"),
            env_file=resolve_project_path(args.env_file),
            artifacts_root=resolve_project_path(args.artifacts_root),
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    raise ValueError(f"Unsupported command: {args.command}")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
