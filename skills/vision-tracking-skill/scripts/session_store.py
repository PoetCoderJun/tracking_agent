#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.session_store import SessionStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect a tracking session on disk.")
    parser.add_argument("--sessions-root", required=True, help="Directory containing session folders")
    parser.add_argument("--session-id", required=True, help="Session identifier")
    parser.add_argument(
        "--show-memory",
        action="store_true",
        help="Print the current memory after the session summary.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = SessionStore(Path(args.sessions_root))
    session = store.load_session(args.session_id)
    print(json.dumps(asdict(session), indent=2, ensure_ascii=True))
    if args.show_memory:
        print()
        print(store.read_memory(args.session_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
