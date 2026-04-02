#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skills.tracking.core.select import execute_select_tool
from skills.tracking.core.payload import build_tracking_turn_payload, ensure_rewrite_paths_exist


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one deterministic continue-tracking turn.")
    parser.add_argument("--tracking-context-file", default="")
    parser.add_argument("--session-file", default="")
    parser.add_argument("--memory-file", default="")
    parser.add_argument("--user-text", default="继续跟踪")
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tracking_context_file = str(args.tracking_context_file or "").strip()
    select_output = execute_select_tool(
        session_file=None if tracking_context_file else Path(args.session_file),
        memory_file=None if tracking_context_file else Path(args.memory_file),
        tracking_context_file=None if not tracking_context_file else Path(tracking_context_file),
        behavior="track",
        arguments={"user_text": str(args.user_text)},
        env_file=Path(args.env_file),
        artifacts_root=Path(args.artifacts_root),
    )
    payload = ensure_rewrite_paths_exist(build_tracking_turn_payload(select_output))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
