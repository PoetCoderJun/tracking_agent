from __future__ import annotations

from pathlib import Path

from backend.perception.service import LocalPerceptionService
from backend.perception.stream import RobotDetection, RobotFrame, RobotIngestEvent
from backend.runtime_session import AgentSessionStore
from backend.tracking.context import TRACKING_LIFECYCLE_BOUND, TRACKING_LIFECYCLE_INACTIVE
from backend.tracking.loop import supervisor_tracking_step


def _write_perception_frame(
    *,
    state_root: Path,
    frame_id: str,
    image_path: Path,
    detections: list[RobotDetection],
) -> None:
    LocalPerceptionService(state_root).write_observation(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id=frame_id,
                timestamp_ms=1710000000000,
                image_path=str(image_path),
            ),
            detections=detections,
            text="frame",
        )
    )
    LocalPerceptionService(state_root).write_frame_result(
        {
            "frame_id": frame_id,
            "timestamp_ms": 1710000000000,
            "image_path": str(image_path),
            "detections": [
                {
                    "track_id": int(detection.track_id),
                    "bbox": [int(value) for value in detection.bbox],
                    "score": float(detection.score),
                    "label": "person",
                }
                for detection in detections
            ],
        }
    )


def test_supervisor_step_marks_session_inactive_without_active_target(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_001", device_id="robot_01")

    result = supervisor_tracking_step(
        sessions=sessions,
        session_id="sess_001",
        device_id="robot_01",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
        owner_id="e-agent:sess_001",
    )

    assert result["status"] == "idle"
    assert sessions.load("sess_001").skills["tracking"]["lifecycle_status"] == TRACKING_LIFECYCLE_INACTIVE


def test_supervisor_step_skips_when_pi_lease_is_held(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_001", device_id="robot_01")
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"frame")
    _write_perception_frame(
        state_root=state_root,
        frame_id="frame_000001",
        image_path=image_path,
        detections=[],
    )
    sessions.patch_skill_state(
        "sess_001",
        skill_name="tracking",
        patch={
            "latest_target_id": 8,
            "latest_confirmed_frame_path": str(image_path),
            "next_tracking_turn_at": 0,
        },
    )
    sessions.acquire_turn(
        session_id="sess_001",
        owner_id="pi",
        turn_kind="pi:tracking-init",
        request_id="req_001",
        wait=False,
    )

    result = supervisor_tracking_step(
        sessions=sessions,
        session_id="sess_001",
        device_id="robot_01",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
        owner_id="e-agent:sess_001",
    )

    assert result["status"] == "busy"


def test_supervisor_step_dispatches_tracking_and_clears_lease(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_001", device_id="robot_01")
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"frame")
    _write_perception_frame(
        state_root=state_root,
        frame_id="frame_000010",
        image_path=image_path,
        detections=[RobotDetection(track_id=8, bbox=[1, 2, 10, 20], score=0.95)],
    )
    sessions.patch_skill_state(
        "sess_001",
        skill_name="tracking",
        patch={
            "latest_target_id": 8,
            "latest_confirmed_frame_path": str(image_path),
            "next_tracking_turn_at": 0,
        },
    )

    def fake_process_tracking_request_direct(**kwargs):
        return {
            "status": "processed",
            "session_result": {
                "behavior": "track",
                "frame_id": "frame_000010",
                "target_id": 8,
                "found": True,
                "text": "继续跟踪",
            },
        }

    monkeypatch.setattr(
        "backend.tracking.loop.process_tracking_request_direct",
        fake_process_tracking_request_direct,
    )

    result = supervisor_tracking_step(
        sessions=sessions,
        session_id="sess_001",
        device_id="robot_01",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
        owner_id="e-agent:sess_001",
    )

    tracking_state = sessions.load("sess_001").skills["tracking"]
    runner_state = sessions.load("sess_001").runner_state
    assert result["status"] == "tracked"
    assert tracking_state["lifecycle_status"] == TRACKING_LIFECYCLE_BOUND
    assert tracking_state["last_trigger"] == "cadence"
    assert tracking_state["last_completed_frame_id"] == "frame_000010"
    assert runner_state["turn_in_flight"] is False
