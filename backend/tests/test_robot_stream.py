from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from backend.perception import (
    RobotDetection,
    RobotFrame,
    RobotIngestEvent,
    append_event_jsonl,
    event_payload,
    generate_request_id,
    generate_session_id,
    is_camera_source,
    normalize_source,
    parse_frame_rate,
    video_timestamp_seconds,
)


def test_normalize_source_supports_camera_index() -> None:
    assert normalize_source("0") == 0
    assert normalize_source(" 12 ") == 12
    assert normalize_source("backend/tests/fixtures/0045.mp4") == "backend/tests/fixtures/0045.mp4"
    assert is_camera_source(normalize_source("0")) is True
    assert is_camera_source(normalize_source("backend/tests/fixtures/0045.mp4")) is False


def test_generate_session_id_returns_unique_prefixed_value() -> None:
    session_id_a = generate_session_id()
    session_id_b = generate_session_id()

    assert session_id_a.startswith("session_")
    assert session_id_b.startswith("session_")
    assert session_id_a != session_id_b


def test_generate_request_id_returns_unique_prefixed_value() -> None:
    request_id_a = generate_request_id()
    request_id_b = generate_request_id()

    assert request_id_a.startswith("req_")
    assert request_id_b.startswith("req_")
    assert request_id_a != request_id_b


def test_parse_frame_rate_supports_fractional_ffprobe_output() -> None:
    assert parse_frame_rate("30000/1001") == 30000 / 1001
    assert parse_frame_rate("25") == 25.0


def test_video_timestamp_seconds_uses_zero_based_video_time() -> None:
    assert video_timestamp_seconds(frame_index=1, fps=30.0) == 0.0
    assert video_timestamp_seconds(frame_index=91, fps=30.0) == 3.0


def test_append_event_jsonl_writes_serialized_event(tmp_path: Path) -> None:
    event = RobotIngestEvent(
        session_id="sess_001",
        device_id="robot_01",
        frame=RobotFrame(
            frame_id="frame_000001",
            timestamp_ms=1710000000000,
            image_path=str(tmp_path / "frame_000001.jpg"),
        ),
        detections=[
            RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95),
        ],
        text="继续跟踪",
    )

    output_path = tmp_path / "events.jsonl"
    append_event_jsonl(output_path, event)

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["session_id"] == "sess_001"
    assert payload["detections"][0]["track_id"] == 12
    assert payload["frame"]["image_path"].endswith("frame_000001.jpg")


def test_event_payload_can_inline_image_base64(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.jpg"
    Image.new("RGB", (8, 8), color="white").save(image_path, format="JPEG")

    event = RobotIngestEvent(
        session_id="sess_001",
        device_id="robot_01",
        frame=RobotFrame(
            frame_id="frame_000001",
            timestamp_ms=1710000000000,
            image_path=str(image_path),
        ),
        detections=[],
        text="",
    )

    payload = event_payload(event, include_image_base64=True)

    assert payload["frame"]["image_path"] == str(image_path)
    assert isinstance(payload["frame"]["image_base64"], str)
    assert payload["frame"]["image_base64"]
