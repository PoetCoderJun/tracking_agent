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
    assert args.pi_sandbox is False
    assert args.unsafe_no_pi_sandbox is False
    assert args.pi_writable_dir == []


class _FakeProcess:
    def __init__(self, captured: dict[str, object], command: list[str], env: dict[str, str]) -> None:
        captured["command"] = command
        captured["env"] = env
        self._poll_calls = 0
        self._captured = captured

    def poll(self) -> int | None:
        self._poll_calls += 1
        return 0 if self._poll_calls > 1 else None

    def terminate(self) -> None:
        self._captured["terminated"] = True

    def wait(self, timeout: float | None = None) -> int:
        self._captured["wait_timeout"] = timeout
        return 0


def test_main_bootstraps_session_then_supervises_pi(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
    state_root = tmp_path / "state"

    monkeypatch.setattr(
        e_agent.subprocess,
        "Popen",
        lambda command, env: _FakeProcess(captured, command, env),
    )
    monkeypatch.setattr(e_agent, "_sandbox_profile_path", lambda args, env: tmp_path / "pi-readonly.sb")
    monkeypatch.setattr(e_agent, "run_due_tracking_step", lambda **kwargs: {"status": "idle"})

    exit_code = e_agent.main(
        [
            "--state-root",
            str(state_root),
            "--pi-bin",
            "pi",
            "--",
            "--model",
            "gpt-5",
        ]
    )

    active_session = json.loads((state_root / "active_session.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert captured["env"]["ROBOT_AGENT_SESSION_ID"] == active_session["session_id"]
    assert captured["env"]["ROBOT_AGENT_STATE_ROOT"] == str((tmp_path / "state").resolve())
    assert captured["env"]["ROBOT_AGENT_TURN_OWNER_ID"] == "pi"
    command = captured["command"]
    assert command[0] == "pi"
    assert command[1:3] == ["--thinking", "minimal"]
    assert "--no-skills" in command
    assert "--append-system-prompt" in command
    prompt_index = command.index("--append-system-prompt") + 1
    assert "请跟踪穿黑衣服的人" in command[prompt_index]
    assert "ROBOT_AGENT_SESSION_ID" in command[prompt_index]
    assert "--skill" in command
    assert "--model" in command


def test_main_can_enable_pi_sandbox(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        e_agent.subprocess,
        "Popen",
        lambda command, env: _FakeProcess(captured, command, env),
    )
    monkeypatch.setattr(e_agent, "_sandbox_profile_path", lambda args, env: tmp_path / "pi-readonly.sb")
    monkeypatch.setattr(e_agent, "run_due_tracking_step", lambda **kwargs: {"status": "idle"})

    exit_code = e_agent.main(
        [
            "--state-root",
            str(tmp_path / "state"),
            "--pi-bin",
            "pi",
            "--pi-sandbox",
            "--",
            "--model",
            "gpt-5",
        ]
    )

    assert exit_code == 0
    assert captured["command"][:3] == ["/usr/bin/sandbox-exec", "-f", str(tmp_path / "pi-readonly.sb")]


def test_main_respects_explicit_thinking_passthrough(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        e_agent.subprocess,
        "Popen",
        lambda command, env: _FakeProcess(captured, command, env),
    )
    monkeypatch.setattr(e_agent, "_sandbox_profile_path", lambda args, env: tmp_path / "pi-readonly.sb")
    monkeypatch.setattr(e_agent, "run_due_tracking_step", lambda **kwargs: {"status": "idle"})

    exit_code = e_agent.main(
        [
            "--state-root",
            str(tmp_path / "state"),
            "--pi-bin",
            "pi",
            "--",
            "--thinking",
            "high",
            "请跟踪穿黑衣服的人",
        ]
    )

    assert exit_code == 0
    command = captured["command"]
    assert command.count("--thinking") == 1
    assert command[command.index("--thinking") + 1] == "high"
