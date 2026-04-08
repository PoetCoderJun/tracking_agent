from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.project_paths import resolve_project_path
from backend.web_search import run_web_search_turn


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic web search skill turn.")
    parser.add_argument("--query", default="")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--frame-buffer-size", type=int, default=3)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--include-answer", action="store_true")
    args = parser.parse_args(argv)

    payload = run_web_search_turn(
        query=str(args.query),
        session_id=args.session_id,
        state_root=resolve_project_path(args.state_root),
        frame_buffer_size=int(args.frame_buffer_size),
        env_file=resolve_project_path(args.env_file),
        max_results=int(args.max_results),
        include_answer=bool(args.include_answer),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
