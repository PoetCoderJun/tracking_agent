from __future__ import annotations

import json
from pathlib import Path

from scripts.run_tracking_stack import (
    _chat_command,
    _loop_command,
    _loop_command_for_session,
    _perception_command,
    _wait_for_started_session,
    _viewer_command,
    parse_args,
)


def test_parse_args_tracking_stack_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_stack.py",
        ],
    )

    args = parse_args()

    assert args.source == "camera"
    assert args.interval_seconds == 3.0
    assert args.init_text is None
    assert args.startup_timeout_seconds == 60.0
    assert args.no_auto_loop is False
    assert args.no_viewer_stream is False
    assert args.state_root == "./.runtime/agent-runtime"


def test_tracking_stack_builds_perception_loop_and_viewer_commands(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_stack.py",
            "--source",
            "demo.mp4",
            "--session-id",
            "sess_001",
            "--tracker",
            "bytetrack.yaml",
            "--host",
            "0.0.0.0",
            "--port",
            "9001",
        ],
    )

    args = parse_args()
    perception = _perception_command(args)
    loop = _loop_command(args)
    viewer = _viewer_command(args)

    assert "scripts.run_tracking_perception" in perception
    assert "scripts.run_tracking_loop" in loop
    assert "scripts.run_tracking_viewer_stream" in viewer
    assert "--session-id" in perception
    assert "--session-id" in loop
    assert "--session-id" in viewer
    assert "--viewer-host" in loop
    assert "--viewer-port" in loop
    assert "--viewer-poll-interval" in loop
    assert "9001" in loop
    assert "9001" in viewer


def test_tracking_stack_builds_init_chat_command(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_stack.py",
            "--init-text",
            "开始跟踪穿黑衣服的人",
        ],
    )

    args = parse_args()
    command = _chat_command(args, session_id="sess_001", text=args.init_text)

    assert "backend.cli" in command
    assert "chat" in command
    assert "--session-id" in command
    assert "sess_001" in command
    assert "--skill" in command
    assert "tracking" in command


def test_loop_command_for_session_override_replaces_active_session_mode(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["run_tracking_stack.py"])
    args = parse_args()

    command = _loop_command_for_session(args, session_id="sess_from_perception")

    assert command.count("--session-id") == 1
    assert "sess_from_perception" in command


def test_wait_for_started_session_returns_new_session_after_first_frame(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True)
    (state_root / "active_session.json").write_text(
        json.dumps({"session_id": "sess_new"}),
        encoding="utf-8",
    )
    session_dir = state_root / "sessions" / "sess_new"
    session_dir.mkdir(parents=True)
    (session_dir / "session.json").write_text(
        json.dumps({"recent_frames": [{"frame_id": "frame_000000"}]}),
        encoding="utf-8",
    )

    class FakeProcess:
        def poll(self):
            return None

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_stack.py",
            "--state-root",
            str(state_root),
        ],
    )
    args = parse_args()

    session_id = _wait_for_started_session(
        args=args,
        perception_process=FakeProcess(),
        previous_active_session_id="sess_old",
    )

    assert session_id == "sess_new"
