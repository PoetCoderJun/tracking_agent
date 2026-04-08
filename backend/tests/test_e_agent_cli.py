from __future__ import annotations

import json

import scripts.e_agent as e_agent


def test_parse_args_supports_pi_passthrough() -> None:
    args = e_agent.parse_args(
        [
            "--session-id",
            "sess_001",
            "--pi-bin",
            "pi",
            "--",
            "--model",
            "gpt-5",
        ]
    )

    assert args.session_id == "sess_001"
    assert args.pi_bin == "pi"
    assert args.pi_args == ["--", "--model", "gpt-5"]
    assert args.unsafe_no_pi_sandbox is False
    assert args.pi_writable_dir == []


def test_main_bootstraps_session_then_execs_pi(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_execvpe(file: str, command: list[str], env: dict[str, str]) -> None:
        captured["file"] = file
        captured["command"] = command
        captured["env"] = env

    monkeypatch.setattr(e_agent.os, "execvpe", fake_execvpe)
    monkeypatch.setattr(e_agent, "_sandbox_profile_path", lambda args, env: tmp_path / "pi-readonly.sb")

    exit_code = e_agent.main(
        [
            "--state-root",
            str(tmp_path / "state"),
            "--pi-bin",
            "pi",
            "--",
            "--model",
            "gpt-5",
        ]
    )

    active_session = json.loads(((tmp_path / "state") / "active_session.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert captured["file"] == "/usr/bin/sandbox-exec"
    assert captured["env"]["ROBOT_AGENT_SESSION_ID"] == active_session["session_id"]
    assert captured["env"]["ROBOT_AGENT_STATE_ROOT"] == str((tmp_path / "state").resolve())
    command = captured["command"]
    assert command[:3] == ["/usr/bin/sandbox-exec", "-f", str(tmp_path / "pi-readonly.sb")]
    assert "--no-skills" in command
    assert "--skill" in command
    assert "--model" in command


def test_main_can_disable_pi_sandbox(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_execvpe(file: str, command: list[str], env: dict[str, str]) -> None:
        captured["file"] = file
        captured["command"] = command
        captured["env"] = env

    monkeypatch.setattr(e_agent.os, "execvpe", fake_execvpe)

    exit_code = e_agent.main(
        [
            "--state-root",
            str(tmp_path / "state"),
            "--pi-bin",
            "pi",
            "--unsafe-no-pi-sandbox",
            "--",
            "--model",
            "gpt-5",
        ]
    )

    assert exit_code == 0
    assert captured["file"] == "pi"
    assert captured["command"][0] == "pi"
