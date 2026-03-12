from scaffold.cli.run_robot_stream import (
    _should_emit_event,
    _should_emit_video_sample,
    parse_args,
)


def test_parse_args_defaults_interval_to_three_seconds(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_robot_stream.py", "--source", "0"],
    )
    args = parse_args()
    assert args.interval_seconds == 3.0
    assert args.backend_timeout_seconds == 310.0
    assert args.ongoing_text == "持续跟踪"


def test_should_emit_event_respects_frame_and_time_gates() -> None:
    assert _should_emit_event(frame_index=3, sample_every=3, now_monotonic=6.0, next_emit_at=5.0)
    assert not _should_emit_event(frame_index=2, sample_every=3, now_monotonic=6.0, next_emit_at=5.0)
    assert not _should_emit_event(frame_index=3, sample_every=3, now_monotonic=4.9, next_emit_at=5.0)


def test_should_emit_video_sample_uses_video_timeline_only() -> None:
    assert _should_emit_video_sample(
        frame_index=91,
        sample_every=1,
        fps=30.0,
        next_video_emit_at=3.0,
    )
    assert not _should_emit_video_sample(
        frame_index=90,
        sample_every=1,
        fps=30.0,
        next_video_emit_at=3.0,
    )
