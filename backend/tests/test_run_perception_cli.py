from __future__ import annotations

from pathlib import Path

from PIL import Image

from backend.perception import LocalPerceptionService, RobotFrame, RobotIngestEvent
from scripts.run_perception import (
    DEFAULT_CAMERA_SOURCE,
    _prepare_perception_writer,
    _should_emit_event,
    _should_emit_video_sample,
    parse_args,
)


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def test_parse_args_defaults_interval_to_one_second(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_perception.py"],
    )
    args = parse_args()
    assert args.source == DEFAULT_CAMERA_SOURCE
    assert args.interval_seconds == 1.0
    assert args.observation_text == ""
    assert args.state_root == "./.runtime/agent-runtime"
    assert args.observation_window_seconds == 5.0
    assert args.keyframe_retention_seconds == 10.0


def test_parse_args_accepts_local_runtime_paths(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_perception.py",
            "--source",
            "0",
            "--state-root",
            "./.runtime/custom-state",
            "--vid-stride",
            "3",
        ],
    )
    args = parse_args()

    assert args.state_root == "./.runtime/custom-state"
    assert args.vid_stride == 3


def test_prepare_perception_writer_always_resets_snapshot(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    perception = LocalPerceptionService(state_root=state_root)
    frame_path = _frame_image(tmp_path / "frame.jpg")
    perception.write_observation(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(frame_id="frame_000001", timestamp_ms=1000, image_path=str(frame_path)),
            detections=[],
            text="camera observation",
        ),
    )

    _prepare_perception_writer(perception_service=perception)

    snapshot = perception.read_snapshot()
    assert snapshot["latest_frame"] is None
    assert snapshot["latest_camera_observation"] is None
    assert snapshot["saved_keyframes"] == []
    assert snapshot["stream_status"]["status"] == "running"


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
