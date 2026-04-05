#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STACK_SCRIPT = ROOT / "scripts" / "run_tracking_stack.sh"
HELP_TEXT = """Usage: robot-agent-tracking-stack [options]

Start the tracking stack environment (perception + backend websocket + tracking backend).

Common options:
  --source <video-or-camera>
  --state-root <path>
  --output-dir <path>
  --artifacts-root <path>
  --device <cpu|mps|cuda>
  --tracker <yaml>
  --session-id <id>
  --init-text <text>
  --realtime-playback
  --start-frontend

Current recommended flow:
  1. Start the stack without forcing init.
  2. Send one init turn separately with `robot-agent chat` or `robot-agent tracking-init`.
  3. Use `robot-agent tracking-track` for deterministic single-step tracking tests.
"""


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(HELP_TEXT)
        return 0
    completed = subprocess.run(
        ["bash", str(STACK_SCRIPT), *sys.argv[1:]],
        cwd=ROOT,
        check=False,
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
