"""Action executors exposed as callable capabilities."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


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


DEFAULT_SPEECH_COMMAND = "/usr/bin/say"


def _command_prefix(command_prefix: Optional[Iterable[str]]) -> List[str]:
    if command_prefix is None:
        return [DEFAULT_SPEECH_COMMAND]
    if isinstance(command_prefix, str):
        return [chunk for chunk in shlex.split(command_prefix) if chunk]
    return [str(chunk).strip() for chunk in command_prefix if str(chunk).strip()]


def build_speak_command(
    *,
    text: str,
    command_prefix: Optional[Iterable[str]] = None,
) -> RobotCliCommand:
    cleaned_text = str(text).strip()
    if not cleaned_text:
        raise ValueError("speech text must not be empty")
    argv = [*_command_prefix(command_prefix), cleaned_text]
    return RobotCliCommand(
        name="speech",
        argv=argv,
        timeout_seconds=30.0,
    )


def execute_speak(
    *,
    text: str,
    command_prefix: Optional[Iterable[str]] = None,
    dry_run: bool = False,
) -> RobotCliCommandResult:
    command = build_speak_command(text=text, command_prefix=command_prefix)
    return RobotCliExecutor(dry_run=dry_run).execute(command)


__all__ = [
    "build_speak_command",
    "DEFAULT_SPEECH_COMMAND",
    "execute_speak",
    "RobotCliCommand",
    "RobotCliCommandResult",
    "RobotCliExecutor",
]
