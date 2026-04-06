from backend.tracking.loop import (
    _bound_status_signature,
    _should_allow_bound_rewrite,
    _should_review_bound_target,
    _non_target_track_ids,
    _has_active_target,
    _next_dispatch_deadline,
    _should_schedule_rewrite,
    _should_request_track_for_frame,
    _stream_completed,
    _track_id_present_in_frame,
    _waiting_for_user,
    parse_args,
)


def test_parse_args_defaults_tracking_loop_runtime(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".ENV"
    env_path.write_text(
        "\n".join(
            [
                "QUERY_INTERVAL_SECONDS=3",
                "TRACKING_IDLE_SLEEP_SECONDS=3",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_loop.py", "--session-id", "sess_001", "--env-file", str(env_path)],
    )

    args = parse_args()

    assert args.session_id == "sess_001"
    assert args.interval_seconds == 3.0
    assert args.recovery_interval_seconds == 1.0
    assert args.idle_sleep_seconds == 3.0
    assert args.presence_check_seconds == 1.0
    assert args.rewrite_interval_seconds == 2.0
    assert args.continue_text == "继续跟踪"
    assert args.state_root == "./.runtime/agent-runtime"
    assert args.stop_file is None


def test_parse_args_tracking_loop_reads_intervals_from_env(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".ENV"
    env_path.write_text(
        "\n".join(
            [
                "QUERY_INTERVAL_SECONDS=7",
                "TRACKING_RECOVERY_INTERVAL_SECONDS=1.5",
                "TRACKING_IDLE_SLEEP_SECONDS=4",
                "TRACKING_MEMORY_REWRITE_INTERVAL_SECONDS=2.5",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_loop.py", "--env-file", str(env_path)],
    )

    args = parse_args()

    assert args.interval_seconds == 7.0
    assert args.recovery_interval_seconds == 1.5
    assert args.idle_sleep_seconds == 4.0
    assert args.rewrite_interval_seconds == 2.5


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
        ],
    )

    args = parse_args()

    assert args.state_root == "./.runtime/custom-state"
    assert args.artifacts_root == "./.runtime/custom-artifacts"


def test_has_active_target_detects_tracking_state() -> None:
    assert _has_active_target({"latest_target_id": 7, "latest_confirmed_frame_path": "/tmp/frame.jpg"}) is True
    assert _has_active_target({"latest_memory": "foo"}) is False
    assert _has_active_target({"latest_target_id": 7}) is False
    assert _has_active_target({"initialized_frame": "frame_000000"}) is False
    assert _has_active_target({}) is False


def test_waiting_for_user_detects_pending_question() -> None:
    assert _waiting_for_user({"pending_question": "Which person?"}) is True
    assert _waiting_for_user({"pending_question": ""}) is False
    assert _waiting_for_user({"pending_question": None}) is False


def test_track_id_present_in_frame_detects_bound_target() -> None:
    frame = {"detections": [{"track_id": 7}, {"track_id": 9}]}
    assert _track_id_present_in_frame(frame, 7) is True
    assert _track_id_present_in_frame(frame, 8) is False


def test_non_target_track_ids_excludes_only_bound_target() -> None:
    frame = {"detections": [{"track_id": 3}, {"track_id": 7}, {"track_id": 12}]}
    assert _non_target_track_ids(frame, 7) == {3, 12}


def test_next_dispatch_deadline_starts_after_interval() -> None:
    assert _next_dispatch_deadline(None, interval_seconds=3.0, now=10.0) == 13.0


def test_next_dispatch_deadline_does_not_add_extra_delay_after_slow_turn() -> None:
    assert _next_dispatch_deadline(13.0, interval_seconds=3.0, now=40.0) == 40.0


def test_next_dispatch_deadline_preserves_regular_cadence_when_not_overdue() -> None:
    assert _next_dispatch_deadline(13.0, interval_seconds=3.0, now=14.0) == 16.0


def test_bound_status_signature_uses_frame_and_target() -> None:
    assert _bound_status_signature({"frame_id": "frame_000123"}, 54) == ("frame_000123", 54)
    assert _bound_status_signature({}, 54) == (None, 54)


def test_should_schedule_rewrite_uses_only_time_gate() -> None:
    assert _should_schedule_rewrite(next_rewrite_at=None, now=10.0) is True
    assert _should_schedule_rewrite(next_rewrite_at=9.0, now=10.0) is True
    assert _should_schedule_rewrite(next_rewrite_at=11.0, now=10.0) is False


def test_stream_completed_detects_completed_status() -> None:
    assert _stream_completed({"status": "completed"}) is True
    assert _stream_completed({"status": "running"}) is False
    assert _stream_completed({}) is False


def test_should_request_track_only_for_new_frames() -> None:
    assert _should_request_track_for_frame(latest_frame_id="frame_000010", last_track_frame_id=None) is True
    assert _should_request_track_for_frame(latest_frame_id="frame_000010", last_track_frame_id="frame_000009") is True
    assert _should_request_track_for_frame(latest_frame_id="frame_000010", last_track_frame_id="frame_000010") is False
    assert _should_request_track_for_frame(latest_frame_id=None, last_track_frame_id="frame_000010") is False


def test_should_review_bound_target_reviews_dense_then_sparse() -> None:
    assert _should_review_bound_target(
        has_competing_detections=True,
        stable_bound_frames=1,
        latest_frame_id="frame_000001",
        last_review_frame_id=None,
    ) is True
    assert _should_review_bound_target(
        has_competing_detections=True,
        stable_bound_frames=2,
        latest_frame_id="frame_000002",
        last_review_frame_id="frame_000001",
    ) is True
    assert _should_review_bound_target(
        has_competing_detections=True,
        stable_bound_frames=4,
        latest_frame_id="frame_000004",
        last_review_frame_id="frame_000003",
    ) is False
    assert _should_review_bound_target(
        has_competing_detections=True,
        stable_bound_frames=11,
        latest_frame_id="frame_000011",
        last_review_frame_id="frame_000010",
    ) is True
    assert _should_review_bound_target(
        has_competing_detections=False,
        stable_bound_frames=1,
        latest_frame_id="frame_000001",
        last_review_frame_id=None,
    ) is False


def test_should_allow_bound_rewrite_requires_confirmed_stability() -> None:
    assert _should_allow_bound_rewrite(review_confirmed=False, stable_bound_frames=10) is False
    assert _should_allow_bound_rewrite(review_confirmed=True, stable_bound_frames=1) is False
    assert _should_allow_bound_rewrite(review_confirmed=True, stable_bound_frames=3) is True
