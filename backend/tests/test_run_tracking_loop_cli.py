from scripts.run_tracking_loop import (
    _has_active_target,
    _waiting_for_user,
    parse_args,
)


def test_parse_args_defaults_tracking_loop_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_loop.py", "--session-id", "sess_001"],
    )

    args = parse_args()

    assert args.session_id == "sess_001"
    assert args.interval_seconds == 3.0
    assert args.idle_sleep_seconds == 1.0
    assert args.continue_text == "继续跟踪"
    assert args.state_root == "./.runtime/agent-runtime"
    assert args.viewer_host == "127.0.0.1"
    assert args.viewer_port == 8765
    assert args.viewer_poll_interval == 1.0
    assert args.no_viewer_stream is False


def test_parse_args_tracking_loop_allows_active_session_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_loop.py"],
    )

    args = parse_args()

    assert args.session_id is None
    assert args.state_root == "./.runtime/agent-runtime"


def test_parse_args_accepts_runtime_paths(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_loop.py",
            "--session-id",
            "sess_001",
            "--state-root",
            "./.runtime/custom-state",
            "--artifacts-root",
            "./.runtime/custom-artifacts",
            "--viewer-host",
            "0.0.0.0",
            "--viewer-port",
            "9001",
        ],
    )

    args = parse_args()

    assert args.state_root == "./.runtime/custom-state"
    assert args.artifacts_root == "./.runtime/custom-artifacts"
    assert args.viewer_host == "0.0.0.0"
    assert args.viewer_port == 9001


def test_has_active_target_detects_tracking_state() -> None:
    assert _has_active_target({"latest_target_id": 7}) is True
    assert _has_active_target({"latest_memory": "foo"}) is True
    assert _has_active_target({}) is False


def test_waiting_for_user_detects_pending_question() -> None:
    assert _waiting_for_user({"pending_question": "Which person?"}) is True
    assert _waiting_for_user({"pending_question": ""}) is False
    assert _waiting_for_user({"pending_question": None}) is False
