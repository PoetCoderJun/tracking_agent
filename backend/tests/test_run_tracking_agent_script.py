from __future__ import annotations

from backend.tracking.service import _chat_command, _loop_command, parse_args


def test_parse_args_tracking_agent_reads_runtime_intervals_from_env(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".ENV"
    env_path.write_text(
        "\n".join(
            [
                "QUERY_INTERVAL_SECONDS=6",
                "TRACKING_RECOVERY_INTERVAL_SECONDS=1.5",
                "TRACKING_IDLE_SLEEP_SECONDS=4",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_agent.py", "--env-file", str(env_path), "--init-text", "开始跟踪"],
    )

    args = parse_args()

    assert args.interval_seconds == 6.0
    assert args.recovery_interval_seconds == 1.5
    assert args.idle_sleep_seconds == 4.0
    assert args.init_text == "开始跟踪"


def test_loop_command_includes_optional_runtime_args() -> None:
    class Args:
        device_id = "robot_01"
        state_root = "./.runtime/custom-state"
        env_file = ".ENV"
        artifacts_root = "./.runtime/custom-artifacts"
        pi_binary = "pi"
        continue_text = "继续跟踪"
        interval_seconds = 3.0
        recovery_interval_seconds = 1.0
        idle_sleep_seconds = 2.0
        presence_check_seconds = 1.0
        session_id = "sess_001"
        max_turns = 5
        stop_file = "/tmp/stop"

    command = _loop_command(Args())

    assert command[:4] == [command[0], "-m", "backend.tracking.loop", "--device-id"]
    assert "--session-id" in command
    assert "--max-turns" in command
    assert "--stop-file" in command


def test_chat_command_routes_through_backend_cli_with_tracking_skill() -> None:
    class Args:
        device_id = "robot_01"
        state_root = "./.runtime/agent-runtime"
        artifacts_root = "./.runtime/pi-agent"
        env_file = ".ENV"
        pi_binary = "pi"

    command = _chat_command(Args(), session_id="sess_001", text="继续跟踪")

    assert command[:4] == [command[0], "-m", "backend.cli", "chat"]
    assert command[-2:] == ["--skill", "tracking"]
