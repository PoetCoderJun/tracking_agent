from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image

from backend.perception import LocalPerceptionService
from backend.system1 import LocalSystem1Service
from scripts.write_environment import (
    DEFAULT_CAMERA_SOURCE,
    DEFAULT_SYSTEM1_MODEL,
    DEFAULT_SYSTEM1_TRACKER,
    _prepare_environment_writer,
    _perception_log_line,
    _run_environment_writer,
    _system1_log_line,
    _should_emit_event,
    _should_emit_video_sample,
    parse_args,
)


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


class _FakeTracker:
    def model_info(self) -> dict:
        return {
            "model_path": "/tmp/yolov8n.pt",
            "tracker": "bytetrack.yaml",
            "class_filter": ["person"],
        }

    def track_frame(self, *, frame_id: str, timestamp_ms: int, image_path: Path) -> dict:
        return {
            "frame_id": frame_id,
            "timestamp_ms": timestamp_ms,
            "image_path": str(image_path),
            "detections": [
                {
                    "track_id": 21,
                    "bbox": [5, 6, 30, 40],
                    "score": 0.88,
                    "label": "person",
                }
            ],
        }


def test_parse_args_defaults_environment_runtime(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["write_environment.py"])
    args = parse_args()

    assert args.state_root == "./.runtime/agent-runtime"
    assert args.source == DEFAULT_CAMERA_SOURCE
    assert args.system1_model == DEFAULT_SYSTEM1_MODEL
    assert args.system1_tracker == DEFAULT_SYSTEM1_TRACKER
    assert args.interval_seconds == 1.0
    assert args.observation_window_seconds == 5.0
    assert args.keyframe_retention_seconds == 10.0
    assert args.disable_system1 is False


def test_prepare_environment_writer_resets_perception_and_system1(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    perception = LocalPerceptionService(state_root)
    system1 = LocalSystem1Service(state_root)
    tracker = _FakeTracker()

    _prepare_environment_writer(
        perception_service=perception,
        system1_service=system1,
        system1_tracker=tracker,
    )

    assert perception.read_snapshot()["stream_status"]["status"] == "running"
    assert system1.read_snapshot()["stream_status"]["status"] == "running"


def test_run_environment_writer_writes_perception_and_system1(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    perception = LocalPerceptionService(state_root)
    system1 = LocalSystem1Service(state_root)
    tracker = _FakeTracker()
    frame_path = _frame_image(tmp_path / "input.jpg")

    _prepare_environment_writer(
        perception_service=perception,
        system1_service=system1,
        system1_tracker=tracker,
    )
    args = type(
        "Args",
        (),
        {
            "state_root": str(state_root),
            "sample_every": 1,
            "interval_seconds": 1.0,
            "realtime_playback": False,
            "pause_after_first_event_file": None,
            "max_events": 1,
            "observation_text": "",
        },
    )()

    exit_code = asyncio.run(
        _run_environment_writer(
            args,
            perception_service=perception,
            system1_service=system1,
            system1_tracker=tracker,
            frame_stream=iter([(1, Image.open(frame_path).convert("RGB"))]),
            video_fps=None,
            source_is_camera=True,
        )
    )

    perception_snapshot = perception.read_snapshot()
    system1_snapshot = system1.read_snapshot()
    assert exit_code == 0
    assert perception_snapshot["latest_frame"]["frame_id"] == "frame_000000"
    assert system1_snapshot["latest_frame_result"]["frame_id"] == "frame_000000"
    assert system1_snapshot["latest_frame_result"]["detections"][0]["track_id"] == 21


def test_should_emit_event_respects_frame_and_time_gates() -> None:
    assert _should_emit_event(frame_index=3, sample_every=3, now_monotonic=6.0, next_emit_at=5.0)
    assert not _should_emit_event(frame_index=2, sample_every=3, now_monotonic=6.0, next_emit_at=5.0)
    assert not _should_emit_event(frame_index=3, sample_every=3, now_monotonic=4.9, next_emit_at=5.0)


def test_should_emit_video_sample_uses_video_timeline_only() -> None:
    assert _should_emit_video_sample(frame_index=91, sample_every=1, fps=30.0, next_video_emit_at=3.0)
    assert not _should_emit_video_sample(frame_index=90, sample_every=1, fps=30.0, next_video_emit_at=3.0)


def test_environment_log_lines_use_human_readable_chinese_labels(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.jpg"

    perception_line = _perception_log_line(
        frame_id="frame_000001",
        timestamp_ms=1234,
        image_path=image_path,
    )
    system1_line = _system1_log_line(
        frame_id="frame_000001",
        system1_result={
            "detections": [
                {"track_id": 7},
                {"track_id": None},
            ]
        },
    )

    assert perception_line == f"视觉感知：frame_id=frame_000001, timestamp_ms=1234, image_path={image_path}"
    assert system1_line == "yolo+bytetrack：frame_id=frame_000001, detection_count=2, track_ids=[7]"
