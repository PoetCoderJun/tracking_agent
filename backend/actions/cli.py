from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class RobotCliCommand:
    name: str
    argv: List[str]
    cwd: Optional[Path] = None
    timeout_seconds: float = 30.0
    env: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class RobotCliCommandResult:
    name: str
    argv: List[str]
    returncode: int
    stdout: str
    stderr: str


class RobotCliExecutor:
    def __init__(self, *, dry_run: bool = False):
        self._dry_run = dry_run

    def execute(self, command: RobotCliCommand) -> RobotCliCommandResult:
        if not command.argv:
            raise ValueError("Robot CLI command argv must not be empty")
        if command.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self._dry_run:
            return RobotCliCommandResult(
                name=command.name,
                argv=list(command.argv),
                returncode=0,
                stdout="",
                stderr="",
            )
        completed = subprocess.run(
            command.argv,
            cwd=None if command.cwd is None else str(command.cwd),
            env=command.env,
            capture_output=True,
            text=True,
            timeout=command.timeout_seconds,
            check=False,
        )
        return RobotCliCommandResult(
            name=command.name,
            argv=list(command.argv),
            returncode=int(completed.returncode),
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

