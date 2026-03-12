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
    parser.add_argument("--frame-buffer-size", type=int, default=3)
    parser.add_argument("--env-file", default=".ENV")
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
        env_path=Path(args.env_file),
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
