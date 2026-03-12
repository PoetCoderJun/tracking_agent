import subprocess
import sys
from pathlib import Path
#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACK_SCRIPT = ROOT / "skills" / "vision-tracking-skill" / "scripts" / "track_from_description.py"


if __name__ == "__main__":
    command = [sys.executable, str(TRACK_SCRIPT), *sys.argv[1:]]
    raise SystemExit(subprocess.run(command, cwd=ROOT).returncode)
