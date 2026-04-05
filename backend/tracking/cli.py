#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.tracking.payload import build_tracking_turn_payload, ensure_rewrite_paths_exist
from backend.tracking.select import execute_select_tool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one deterministic tracking command from backend.tracking.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Bind or switch a tracking target deterministically.")
    init_parser.add_argument("--tracking-context-file", default="")
    init_parser.add_argument("--session-file", default="")
    init_parser.add_argument("--target-description", required=True)
    init_parser.add_argument("--env-file", default=".ENV")
    init_parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")

    track_parser = subparsers.add_parser("track", help="Run one deterministic continue-tracking turn.")
    track_parser.add_argument("--tracking-context-file", default="")
    track_parser.add_argument("--session-file", default="")
    track_parser.add_argument("--user-text", default="继续跟踪")
    track_parser.add_argument("--env-file", default=".ENV")
    track_parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")

    return parser.parse_args()


def _payload_for_command(args: argparse.Namespace) -> dict:
    tracking_context_file = str(getattr(args, "tracking_context_file", "") or "").strip()
    session_file = str(getattr(args, "session_file", "") or "").strip()
    behavior = str(args.command).strip()
    arguments = (
        {"target_description": str(args.target_description)}
        if behavior == "init"
        else {"user_text": str(args.user_text)}
    )
    select_output = execute_select_tool(
        session_file=None if tracking_context_file else Path(session_file),
        tracking_context_file=None if not tracking_context_file else Path(tracking_context_file),
        behavior=behavior,
        arguments=arguments,
        env_file=Path(args.env_file),
        artifacts_root=Path(args.artifacts_root),
    )
    return ensure_rewrite_paths_exist(build_tracking_turn_payload(select_output))


def main() -> int:
    args = parse_args()
    print(json.dumps(_payload_for_command(args), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
