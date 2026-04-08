from __future__ import annotations

import backend.tracking.service as service


def test_parse_args_tracking_service_reads_runtime_intervals_from_env(monkeypatch, tmp_path) -> None:
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
    monkeypatch.setattr("sys.argv", ["tracking-service", "--env-file", str(env_path)])

    args = service.parse_args()

    assert args.interval_seconds == 6.0
    assert args.recovery_interval_seconds == 1.5
    assert args.idle_sleep_seconds == 4.0


def test_loop_command_includes_optional_runtime_args() -> None:
    class Args:
        device_id = "robot_01"
        state_root = "./.runtime/custom-state"
        env_file = ".ENV"
        artifacts_root = "./.runtime/custom-artifacts"
        continue_text = "继续跟踪"
        interval_seconds = 3.0
        recovery_interval_seconds = 1.0
        idle_sleep_seconds = 2.0
        presence_check_seconds = 1.0
        session_id = "sess_001"
        max_turns = 5
        stop_file = "/tmp/stop"

    command = service._loop_command(Args())

    assert command[:4] == [service.sys.executable, "-m", "backend.tracking.loop", "--device-id"]
    assert "--session-id" in command
    assert "--max-turns" in command
    assert "--stop-file" in command
