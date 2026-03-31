from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.run_tracking_stack import (
    _chat_command,
    _init_turn_confirmed,
    _json_payload_from_stdout,
    _loop_command,
    _loop_command_for_session,
    _perception_command,
    _tracking_runtime_command,
    _use_standalone_viewer_stream,
    _wait_for_started_session,
    _viewer_command,
    parse_args,
)


def test_parse_args_tracking_stack_defaults(monkeypatch, tmp_path: Path) -> None:
    env_path = tmp_path / ".ENV"
    env_path.write_text(
        "\n".join(
            [
                "PERCEPTION_INTERVAL_SECONDS=1",
                "QUERY_INTERVAL_SECONDS=3",
                "TRACKING_IDLE_SLEEP_SECONDS=3",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_stack.py",
            "--env-file",
            str(env_path),
            "--init-text",
            "开始跟踪穿黑衣服的人",
        ],
    )

    args = parse_args()

    assert args.source == "camera"
    assert args.interval_seconds is None
    assert args.perception_interval_seconds == 1.0
    assert args.query_interval_seconds == 3.0
    assert args.recovery_interval_seconds == 1.0
    assert args.idle_sleep_seconds == 3.0
    assert args.presence_check_seconds == 1.0
    assert args.init_text == "开始跟踪穿黑衣服的人"
    assert args.startup_timeout_seconds == 60.0
    assert args.shutdown_grace_seconds == 60.0
    assert args.no_auto_loop is False
    assert args.no_viewer_stream is False
    assert args.state_root == "./.runtime/agent-runtime"


def test_parse_args_tracking_stack_reads_split_intervals_from_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".ENV"
    env_path.write_text(
        "\n".join(
            [
                "PERCEPTION_INTERVAL_SECONDS=2.5",
                "QUERY_INTERVAL_SECONDS=6",
                "TRACKING_RECOVERY_INTERVAL_SECONDS=1.0",
                "TRACKING_IDLE_SLEEP_SECONDS=4",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_stack.py", "--env-file", str(env_path), "--init-text", "开始跟踪穿黑衣服的人"],
    )

    args = parse_args()

    assert args.perception_interval_seconds == 2.5
    assert args.query_interval_seconds == 6.0
    assert args.recovery_interval_seconds == 1.0
    assert args.idle_sleep_seconds == 4.0


def test_parse_args_tracking_stack_legacy_interval_override_sets_both_intervals(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".ENV"
    env_path.write_text(
        "\n".join(
            [
                "PERCEPTION_INTERVAL_SECONDS=1",
                "QUERY_INTERVAL_SECONDS=3",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_stack.py",
            "--env-file",
            str(env_path),
            "--interval-seconds",
            "8",
            "--init-text",
            "开始跟踪穿黑衣服的人",
        ],
    )

    args = parse_args()

    assert args.interval_seconds == 8.0
    assert args.perception_interval_seconds == 8.0
    assert args.query_interval_seconds == 8.0


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
            "--init-text",
            "开始跟踪穿黑衣服的人",
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
    assert "--pause-after-first-event-file" in perception
    assert "--session-id" in loop
    assert "--session-id" in viewer
    assert "--viewer-host" in loop
    assert "--viewer-port" in loop
    assert "--viewer-poll-interval" in loop
    assert "--recovery-interval-seconds" in loop
    assert "--presence-check-seconds" in loop
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


def test_json_payload_from_stdout_reads_last_json_line() -> None:
    payload = _json_payload_from_stdout("\nignore\n{\"status\":\"processed\"}\n")
    assert payload == {"status": "processed"}


def test_init_turn_confirmed_requires_confirmed_target() -> None:
    assert _init_turn_confirmed(
        {
            "status": "processed",
            "session_result": {
                "target_id": 5,
                "found": True,
                "needs_clarification": False,
            },
        }
    )
    assert not _init_turn_confirmed(
        {
            "status": "processed",
            "session_result": {
                "target_id": None,
                "found": False,
                "needs_clarification": True,
            },
        }
    )


def test_loop_command_for_session_override_replaces_active_session_mode(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["run_tracking_stack.py", "--init-text", "开始跟踪穿黑衣服的人"])
    args = parse_args()

    command = _loop_command_for_session(args, session_id="sess_from_perception")

    assert command.count("--session-id") == 1
    assert "sess_from_perception" in command


def test_tracking_runtime_command_keeps_active_session_mode_without_explicit_session_id(
    monkeypatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["run_tracking_stack.py", "--init-text", "开始跟踪穿黑衣服的人"])
    args = parse_args()

    command = _tracking_runtime_command(args, started_session_id="sess_from_perception")

    assert "--session-id" not in command
    assert "sess_from_perception" not in command


def test_tracking_runtime_command_pins_explicit_session_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_stack.py", "--session-id", "sess_explicit", "--init-text", "开始跟踪穿黑衣服的人"],
    )
    args = parse_args()

    command = _tracking_runtime_command(args, started_session_id="sess_explicit")

    assert command.count("--session-id") == 1
    assert "sess_explicit" in command


def test_tracking_runtime_command_disables_embedded_viewer_when_init_text_present(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_stack.py", "--init-text", "开始跟踪穿黑衣服的人"],
    )
    args = parse_args()

    command = _tracking_runtime_command(args, started_session_id="sess_from_perception")

    assert "--stop-file" in command
    assert "--no-viewer-stream" in command


def test_use_standalone_viewer_stream_only_for_init_tracking_stack(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_stack.py", "--init-text", "开始跟踪穿黑衣服的人"],
    )
    args = parse_args()
    assert _use_standalone_viewer_stream(args) is True

    monkeypatch.setattr("sys.argv", ["run_tracking_stack.py"])
    try:
        parse_args()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("parse_args should require --init-text")

    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_stack.py", "--init-text", "开始跟踪穿黑衣服的人", "--no-viewer-stream"],
    )
    args = parse_args()
    assert _use_standalone_viewer_stream(args) is False


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
            "--init-text",
            "开始跟踪穿黑衣服的人",
        ],
    )
    args = parse_args()

    session_id = _wait_for_started_session(
        args=args,
        perception_process=FakeProcess(),
        previous_active_session_id="sess_old",
    )

    assert session_id == "sess_new"


def test_main_starts_standalone_viewer_then_init_chat_then_tracking_runtime(monkeypatch) -> None:
    import scripts.run_tracking_stack as module

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_stack.py",
            "--init-text",
            "开始跟踪穿黑衣服的人",
        ],
    )

    call_order = []
    seeded_snapshots = []

    class FakeProcess:
        def __init__(self, label: str) -> None:
            self.label = label

        def poll(self):
            return 0

        def terminate(self) -> None:
            return None

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            return None

    def fake_popen(command, cwd=None):
        if "scripts.run_tracking_perception" in command:
            call_order.append("popen:perception")
            return FakeProcess("perception")
        if "scripts.run_tracking_viewer_stream" in command:
            call_order.append("popen:viewer-stream")
            return FakeProcess("viewer-stream")
        if "scripts.run_tracking_loop" in command:
            call_order.append("popen:tracking-runtime")
            return FakeProcess("tracking-runtime")
        raise AssertionError(f"unexpected Popen command: {command}")

    def fake_run(command, cwd=None, check=False, capture_output=False, text=False):
        assert "backend.cli" in command
        call_order.append("run:init-chat")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "processed",
                    "session_result": {
                        "target_id": 5,
                        "found": True,
                        "needs_clarification": False,
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(module, "_wait_for_started_session", lambda **kwargs: "sess_started")
    monkeypatch.setattr(
        module,
        "_first_session_frame_snapshot",
        lambda *_args, **_kwargs: {"frame_id": "frame_000000", "image_path": "/tmp/frame.jpg", "detections": []},
    )
    class FakeRuntime:
        def __init__(self, state_root):
            self.state_root = state_root

        def update_skill_cache(self, session_id, *, skill_name, payload):
            seeded_snapshots.append((session_id, skill_name, payload))
            return None

    monkeypatch.setattr(module, "LocalAgentRuntime", FakeRuntime)
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "_terminate_processes", lambda processes: None)

    exit_code = module.main()

    assert exit_code == 0
    assert call_order == [
        "popen:perception",
        "popen:viewer-stream",
        "run:init-chat",
        "popen:tracking-runtime",
    ]
    assert seeded_snapshots == [
        (
            "sess_started",
            "tracking",
            {"init_frame_snapshot": {"frame_id": "frame_000000", "image_path": "/tmp/frame.jpg", "detections": []}},
        ),
        ("sess_started", "tracking", {"init_frame_snapshot": None}),
    ]


def test_main_stops_when_init_chat_does_not_confirm_target(monkeypatch) -> None:
    import scripts.run_tracking_stack as module

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_stack.py",
            "--init-text",
            "开始跟踪穿黑衣服的人",
        ],
    )

    call_order = []
    seeded_snapshots = []

    class FakeProcess:
        def __init__(self, label: str) -> None:
            self.label = label

        def poll(self):
            return 0

        def terminate(self) -> None:
            return None

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            return None

    def fake_popen(command, cwd=None):
        if "scripts.run_tracking_perception" in command:
            call_order.append("popen:perception")
            return FakeProcess("perception")
        if "scripts.run_tracking_viewer_stream" in command:
            call_order.append("popen:viewer-stream")
            return FakeProcess("viewer-stream")
        if "scripts.run_tracking_loop" in command:
            call_order.append("popen:tracking-runtime")
            return FakeProcess("tracking-runtime")
        raise AssertionError(f"unexpected Popen command: {command}")

    def fake_run(command, cwd=None, check=False, capture_output=False, text=False):
        assert "backend.cli" in command
        call_order.append("run:init-chat")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "processed",
                    "session_result": {
                        "target_id": None,
                        "found": False,
                        "needs_clarification": True,
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(module, "_wait_for_started_session", lambda **kwargs: "sess_started")
    monkeypatch.setattr(
        module,
        "_first_session_frame_snapshot",
        lambda *_args, **_kwargs: {"frame_id": "frame_000000", "image_path": "/tmp/frame.jpg", "detections": []},
    )
    class FakeRuntime:
        def __init__(self, state_root):
            self.state_root = state_root

        def update_skill_cache(self, session_id, *, skill_name, payload):
            seeded_snapshots.append((session_id, skill_name, payload))
            return None

    monkeypatch.setattr(module, "LocalAgentRuntime", FakeRuntime)
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "_terminate_processes", lambda processes: None)

    exit_code = module.main()

    assert exit_code == 1
    assert call_order == [
        "popen:perception",
        "popen:viewer-stream",
        "run:init-chat",
    ]
    assert seeded_snapshots == [
        (
            "sess_started",
            "tracking",
            {"init_frame_snapshot": {"frame_id": "frame_000000", "image_path": "/tmp/frame.jpg", "detections": []}},
        ),
        ("sess_started", "tracking", {"init_frame_snapshot": None}),
    ]
