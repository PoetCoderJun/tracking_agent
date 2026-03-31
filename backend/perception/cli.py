#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from backend.perception.service import LocalPerceptionService
from backend.persistence import resolve_session_id
from backend.project_paths import resolve_project_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read persisted perception state through the shared storage interface."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    read_parser = subparsers.add_parser(
        "read",
        help="Print the current persisted perception snapshot for one session.",
    )
    read_parser.add_argument("--session-id", default=None)
    read_parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    read_parser.add_argument("--frame-buffer-size", type=int, default=3)

    latest_frame_parser = subparsers.add_parser(
        "latest-frame",
        help="Print only the latest persisted frame for one session.",
    )
    latest_frame_parser.add_argument("--session-id", default=None)
    latest_frame_parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    latest_frame_parser.add_argument("--frame-buffer-size", type=int, default=3)

    return parser.parse_args()


def _resolved_session_id(args: argparse.Namespace) -> str:
    session_id = resolve_session_id(
        state_root=resolve_project_path(args.state_root),
        session_id=args.session_id,
    )
    if session_id is None:
        raise ValueError("No active session found. Pass --session-id or start perception first.")
    return session_id


def main() -> int:
    args = parse_args()
    state_root = resolve_project_path(args.state_root)
    service = LocalPerceptionService(
        state_root=state_root,
        frame_buffer_size=args.frame_buffer_size,
    )
    session_id = _resolved_session_id(args)

    if args.command == "read":
        print(json.dumps(service.read_snapshot(session_id), ensure_ascii=False))
        return 0
    if args.command == "latest-frame":
        print(json.dumps(service.read_latest_frame(session_id), ensure_ascii=False))
        return 0
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
