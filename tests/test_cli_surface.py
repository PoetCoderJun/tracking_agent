from __future__ import annotations

from capabilities.tracking import benchmark as tracking_benchmark
from world import write_environment


def test_write_environment_uses_realtime_playback_for_file_source() -> None:
    args = write_environment.parse_args(["--source", "tests/fixtures/demo_video.mp4"])

    assert args.source == "tests/fixtures/demo_video.mp4"
    assert args.realtime_playback is True


def test_write_environment_keeps_camera_defaults_simple() -> None:
    args = write_environment.parse_args(["--source", "0"])

    assert args.source == "0"
    assert args.realtime_playback is False


def test_tracking_benchmark_parse_args_has_no_pipeline_option() -> None:
    args = tracking_benchmark.parse_args([])

    assert not hasattr(args, "pipeline")
