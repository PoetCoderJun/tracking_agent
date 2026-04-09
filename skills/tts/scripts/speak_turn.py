from __future__ import annotations

import argparse
import json
from typing import List, Optional

from backend.project_paths import resolve_project_path
from backend.tts import run_tts_turn


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic TTS skill turn.")
    parser.add_argument("--text", default="")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    args = parser.parse_args(argv)

    payload = run_tts_turn(
        text=str(args.text),
        session_id=args.session_id,
        state_root=resolve_project_path(args.state_root),
        env_file=resolve_project_path(args.env_file),
        artifacts_root=resolve_project_path(args.artifacts_root),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
