#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.project_paths import resolve_project_path
from backend.agent_viewer_stream import AgentViewerStreamServer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the agent viewer websocket stream for one session or the active session."
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, follows the current active session.",
    )
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = AgentViewerStreamServer(
        state_root=resolve_project_path(args.state_root),
        session_id=args.session_id,
        host=args.host,
        port=args.port,
        poll_interval=args.poll_interval,
    )
    asyncio.run(server.serve_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
