from __future__ import annotations

from pathlib import Path

from backend.system1 import LocalSystem1Service


def _frame_result(*, frame_id: str, timestamp_ms: int, image_path: Path, track_id: int | None) -> dict:
    return {
        "frame_id": frame_id,
        "timestamp_ms": timestamp_ms,
        "image_path": str(image_path),
        "detections": [
            {
                "track_id": track_id,
                "bbox": [10, 20, 30, 40],
                "score": 0.95,
                "label": "person",
            }
        ],
    }


def test_system1_service_keeps_recent_window_only(tmp_path: Path) -> None:
    service = LocalSystem1Service(tmp_path / "state", result_window_seconds=2.0)
    frame_path = tmp_path / "frame.jpg"

    service.write_result(_frame_result(frame_id="frame_001", timestamp_ms=1000, image_path=frame_path, track_id=1))
    service.write_result(_frame_result(frame_id="frame_002", timestamp_ms=2500, image_path=frame_path, track_id=2))
    service.write_result(_frame_result(frame_id="frame_003", timestamp_ms=4100, image_path=frame_path, track_id=3))

    snapshot = service.read_snapshot()

    assert [item["frame_id"] for item in snapshot["recent_frame_results"]] == ["frame_002", "frame_003"]
    assert snapshot["latest_frame_result"]["frame_id"] == "frame_003"


def test_system1_service_updates_model_and_stream_status(tmp_path: Path) -> None:
    service = LocalSystem1Service(tmp_path / "state")

    service.prepare(
        fresh_state=True,
        model_info={"model_path": "/tmp/yolov8n.pt", "tracker": "bytetrack.yaml"},
    )
    snapshot = service.update_stream_status(status="completed", ended_at_ms=1234)

    assert snapshot["model"]["model_path"] == "/tmp/yolov8n.pt"
    assert snapshot["stream_status"]["status"] == "completed"
    assert snapshot["stream_status"]["ended_at_ms"] == 1234


def test_system1_service_deduplicates_frame_ids(tmp_path: Path) -> None:
    service = LocalSystem1Service(tmp_path / "state")
    frame_path = tmp_path / "frame.jpg"

    service.write_result(_frame_result(frame_id="frame_001", timestamp_ms=1000, image_path=frame_path, track_id=1))
    service.write_result(_frame_result(frame_id="frame_001", timestamp_ms=1000, image_path=frame_path, track_id=7))

    recent = service.recent_frame_results()
    assert len(recent) == 1
    assert recent[0]["detections"][0]["track_id"] == 7
