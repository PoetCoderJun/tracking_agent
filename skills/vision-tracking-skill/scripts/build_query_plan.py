#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUILD_QUERY_PLAN = ROOT / "scaffold" / "cli" / "build_query_plan.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Skill-local wrapper for query-plan construction.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--sample-fps", type=float, default=None)
    parser.add_argument("--query-interval-seconds", type=int, default=None)
    parser.add_argument("--recent-frame-count", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = [
        sys.executable,
        str(BUILD_QUERY_PLAN),
        "--video",
        args.video,
        "--runtime-dir",
        args.runtime_dir,
        "--env-file",
        args.env_file,
    ]
    if args.sample_fps is not None:
        command.extend(["--sample-fps", str(args.sample_fps)])
    if args.query_interval_seconds is not None:
        command.extend(["--query-interval-seconds", str(args.query_interval_seconds)])
    if args.recent_frame_count is not None:
        command.extend(["--recent-frame-count", str(args.recent_frame_count)])
    subprocess.run(command, cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
