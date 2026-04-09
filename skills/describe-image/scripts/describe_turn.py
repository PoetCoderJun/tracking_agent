from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.describe_image import run_describe_turn
from backend.project_paths import resolve_project_path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic image-description skill turn.")
    parser.add_argument("--image-path", default="")
    parser.add_argument("--user-text", default="")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--env-file", default=".ENV")
    args = parser.parse_args(argv)

    payload = run_describe_turn(
        image_path=str(args.image_path),
        user_text=str(args.user_text),
        session_id=args.session_id,
        state_root=resolve_project_path(args.state_root),
        env_file=resolve_project_path(args.env_file),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
