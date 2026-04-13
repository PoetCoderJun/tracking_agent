#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from world.perception.service import LocalPerceptionService
from agent.project_paths import resolve_project_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read persisted perception state through the shared storage interface."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    read_parser = subparsers.add_parser(
        "read",
        help="Print the current persisted global perception snapshot.",
    )
    read_parser.add_argument("--state-root", default="./.runtime/agent-runtime")

    latest_frame_parser = subparsers.add_parser(
        "latest-frame",
        help="Print only the latest persisted frame from the global perception state.",
    )
    latest_frame_parser.add_argument("--state-root", default="./.runtime/agent-runtime")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state_root = resolve_project_path(args.state_root)
    service = LocalPerceptionService(state_root=state_root)

    if args.command == "read":
        print(json.dumps(service.read_snapshot(), ensure_ascii=False))
        return 0
    if args.command == "latest-frame":
        print(json.dumps(service.read_latest_frame(), ensure_ascii=False))
        return 0
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
