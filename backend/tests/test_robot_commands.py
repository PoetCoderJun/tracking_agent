from __future__ import annotations

from backend.actions import RobotCliCommand, RobotCliExecutor


def test_robot_cli_executor_supports_dry_run() -> None:
    executor = RobotCliExecutor(dry_run=True)

    result = executor.execute(
        RobotCliCommand(
            name="navigate",
            argv=["echo", "forward"],
        )
    )

    assert result.name == "navigate"
    assert result.returncode == 0
    assert result.argv == ["echo", "forward"]
