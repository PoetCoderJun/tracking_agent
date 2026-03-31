from scripts.run_tracking_agent import _loop_command, parse_args


def test_parse_args_tracking_agent_defaults(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".ENV"
    env_path.write_text(
        "\n".join(
            [
                "QUERY_INTERVAL_SECONDS=3",
                "TRACKING_RECOVERY_INTERVAL_SECONDS=1",
                "TRACKING_IDLE_SLEEP_SECONDS=3",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_agent.py", "--env-file", str(env_path)],
    )

    args = parse_args()

    assert args.interval_seconds == 3.0
    assert args.recovery_interval_seconds == 1.0
    assert args.idle_sleep_seconds == 3.0
    assert args.init_text == ""
    assert args.startup_timeout_seconds == 60.0


def test_loop_command_disables_embedded_viewer_stream(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_agent.py", "--session-id", "sess_001", "--init-text", "开始跟踪"],
    )

    args = parse_args()
    command = _loop_command(args)

    assert "scripts.run_tracking_loop" in command
    assert "--no-viewer-stream" in command
    assert "--session-id" in command
    assert "sess_001" in command
