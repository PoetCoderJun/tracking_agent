from __future__ import annotations

import os

import scripts.run_tracking_stack as run_tracking_stack


def test_main_prints_help(capsys) -> None:
    original_argv = run_tracking_stack.sys.argv
    run_tracking_stack.sys.argv = ["robot-agent-tracking-stack", "--help"]
    try:
        exit_code = run_tracking_stack.main()
    finally:
        run_tracking_stack.sys.argv = original_argv

    assert exit_code == 0
    assert "Usage: robot-agent-tracking-stack" in capsys.readouterr().out


def test_main_execs_stack_script(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_execvpe(file: str, command: list[str], env: dict[str, str]) -> None:
        captured["file"] = file
        captured["command"] = command
        captured["env"] = env

    monkeypatch.setattr(run_tracking_stack.os, "execvpe", fake_execvpe)
    monkeypatch.setattr(run_tracking_stack.sys, "argv", ["robot-agent-tracking-stack", "--source", "0"])

    exit_code = run_tracking_stack.main()

    assert exit_code == 0
    assert captured["file"] == "bash"
    assert captured["command"] == [
        "bash",
        str(run_tracking_stack.STACK_SCRIPT),
        "--source",
        "0",
    ]
    assert captured["env"] == os.environ.copy()
