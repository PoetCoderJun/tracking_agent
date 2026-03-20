#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the minimal tracking backend.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--state-root", default="./runtime/backend")
    parser.add_argument(
        "--public-base-url",
        default=None,
        help="Public backend base URL used in API payloads, for example https://tracking.example.com.",
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        dest="allow_origins",
        default=None,
        help="Allowed frontend origin. Repeat the flag to allow multiple origins. Defaults to '*'.",
    )
    parser.add_argument(
        "--frontend-dist",
        default=None,
        help="Optional built frontend directory to serve from the backend, for example ./frontend/dist.",
    )
    parser.add_argument("--frame-buffer-size", type=int, default=3)
    parser.add_argument(
        "--external-agent-wait-seconds",
        type=float,
        default=300.0,
        help="How long /robot/ingest should wait for an external /agent-result before replying.",
    )
    parser.add_argument(
        "--external-agent-poll-seconds",
        type=float,
        default=0.1,
        help="Legacy compatibility flag. Backend now waits for external /agent-result using in-process events.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "Missing backend dependencies. Install requirements.txt before running run_backend.py."
        ) from exc
    try:
        from tracking_agent.backend_api import create_app
    except ImportError as exc:
        raise RuntimeError(
            "Missing backend API dependencies. Install requirements.txt before running run_backend.py."
        ) from exc

    app = create_app(
        state_root=Path(args.state_root),
        frame_buffer_size=args.frame_buffer_size,
        external_agent_wait_seconds=args.external_agent_wait_seconds,
        external_agent_poll_seconds=args.external_agent_poll_seconds,
        public_base_url=args.public_base_url,
        cors_origins=args.allow_origins,
        frontend_dist=None if args.frontend_dist in (None, "") else Path(args.frontend_dist),
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
