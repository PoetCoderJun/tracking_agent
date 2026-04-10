#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STACK_SCRIPT = ROOT / "scripts" / "run_tracking_stack.sh"
HELP_TEXT = """Usage: robot-agent-tracking-stack [options]

Start the tracking stack environment (environment writer + viewer websocket).

Common options:
  --source <video-or-camera>
  --state-root <path>
  --realtime-playback
  --start-frontend

Current recommended flow:
  1. Start the stack to launch the environment writer workflow.
  2. Start the main runner with `e-agent`.
  3. Let `pi` run the conversation loop and call project skills directly.
  4. Successful `tracking-init` in `pi` will activate continuous tracking inside the same `e-agent` session supervisor.
  5. Use `robot-agent tracking-init` / `robot-agent tracking-track` only for deterministic backend checks.
"""


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(HELP_TEXT)
        return 0
    command = ["bash", str(STACK_SCRIPT), *sys.argv[1:]]
    try:
        os.execvpe(command[0], command, os.environ.copy())
        return 0
    except FileNotFoundError as exc:
        raise RuntimeError(f"bash executable not found: {command[0]}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
