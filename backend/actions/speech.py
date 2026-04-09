from __future__ import annotations

import shlex
from typing import Iterable, List, Optional

from backend.actions.cli import RobotCliCommand, RobotCliCommandResult, RobotCliExecutor

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
