"""Action executors exposed by the backend."""

from backend.actions.cli import RobotCliCommand, RobotCliCommandResult, RobotCliExecutor
from backend.actions.speech import DEFAULT_SPEECH_COMMAND, build_speak_command, execute_speak

__all__ = [
    "build_speak_command",
    "DEFAULT_SPEECH_COMMAND",
    "execute_speak",
    "RobotCliCommand",
    "RobotCliCommandResult",
    "RobotCliExecutor",
]
