from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_server_management_scripts_exist_and_are_executable() -> None:
    script_paths = [
        ROOT / "scripts" / "server_start.sh",
        ROOT / "scripts" / "server_stop.sh",
        ROOT / "scripts" / "server_watch.sh",
    ]

    for path in script_paths:
        assert path.exists()
        assert path.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
        assert os.access(path, os.X_OK)
