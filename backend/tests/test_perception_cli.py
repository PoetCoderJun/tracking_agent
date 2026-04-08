from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from backend.perception import LocalPerceptionService, RobotDetection, RobotFrame, RobotIngestEvent
from backend.perception.cli import main, parse_args


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def test_parse_args_reads_snapshot_command(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["perception.py", "read", "--state-root", "./.runtime/state"],
    )
    args = parse_args()
    assert args.command == "read"
    assert args.state_root == "./.runtime/state"


def test_local_perception_service_persists_observation_snapshot(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    frame_path = _frame_image(tmp_path / "frame.jpg")
    service = LocalPerceptionService(state_root=state_root)
    service.prepare(fresh_state=True)

    snapshot = service.write_observation(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[RobotDetection(track_id=7, bbox=[10, 12, 40, 44], score=0.9)],
            text="camera observation",
        ),
        request_id="req_obs_001",
        request_function="observation",
    )

    assert snapshot["latest_camera_observation"]["id"] == "frame_000001"
    assert snapshot["latest_person_detection"]["payload"]["detections"][0]["track_id"] == 7
    assert snapshot["saved_keyframes"]


def test_perception_cli_prints_latest_frame(monkeypatch, tmp_path: Path, capsys) -> None:
    state_root = tmp_path / "state"
    frame_path = _frame_image(tmp_path / "frame.jpg")
    service = LocalPerceptionService(state_root=state_root)
    service.prepare(fresh_state=True)
    service.write_observation(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[],
            text="",
        ),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "perception.py",
            "latest-frame",
            "--state-root",
            str(state_root),
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["frame_id"] == "frame_000001"
