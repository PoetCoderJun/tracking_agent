from __future__ import annotations

from pathlib import Path

from PIL import Image

from world.perception import LocalPerceptionService, RobotDetection, RobotFrame, RobotIngestEvent
from agent.session import AgentSessionStore
from capabilities.tracking.runtime.triggers import derive_continuous_trigger
from capabilities.tracking.runtime.types import TRIGGER_CADENCE_REVIEW, TRIGGER_EVENT_REBIND


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def _write_observation(*, state_root: Path, session_id: str, frame_id: str, image_path: Path, detections: list[RobotDetection]) -> None:
    perception = LocalPerceptionService(state_root)
    perception.write_observation(
        RobotIngestEvent(
            session_id=session_id,
            device_id="robot_01",
            frame=RobotFrame(
                frame_id=frame_id,
                timestamp_ms=1710000000000,
                image_path=str(image_path),
            ),
            detections=detections,
            text="tracking",
        )
    )


def test_derive_continuous_trigger_returns_cadence_review_when_due_and_target_present(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking",
        patch={
            "latest_target_id": 15,
            "next_tracking_turn_at": 0.0,
            "last_completed_frame_id": "",
            "lifecycle_status": "bound",
        },
    )
    image_path = _frame_image(tmp_path / "frame.jpg")
    _write_observation(
        state_root=state_root,
        session_id="sess_tracking",
        frame_id="frame_000001",
        image_path=image_path,
        detections=[RobotDetection(track_id=15, bbox=[10, 12, 36, 44], score=0.95)],
    )

    trigger = derive_continuous_trigger(sessions.load("sess_tracking"))

    assert trigger is not None
    assert trigger.type == TRIGGER_CADENCE_REVIEW
    assert trigger.cause == "new_snapshot"


def test_derive_continuous_trigger_returns_event_rebind_when_target_missing(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking",
        patch={
            "latest_target_id": 15,
            "next_tracking_turn_at": 9999999999.0,
            "last_completed_frame_id": "",
            "lifecycle_status": "bound",
        },
    )
    image_path = _frame_image(tmp_path / "frame.jpg")
    _write_observation(
        state_root=state_root,
        session_id="sess_tracking",
        frame_id="frame_000001",
        image_path=image_path,
        detections=[RobotDetection(track_id=18, bbox=[10, 12, 36, 44], score=0.95)],
    )

    trigger = derive_continuous_trigger(sessions.load("sess_tracking"))

    assert trigger is not None
    assert trigger.type == TRIGGER_EVENT_REBIND
    assert trigger.cause == "target_missing"


def test_derive_continuous_trigger_returns_none_when_waiting_for_user(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking",
        patch={
            "latest_target_id": 15,
            "pending_question": "请确认目标。",
            "next_tracking_turn_at": 0.0,
            "last_completed_frame_id": "",
            "lifecycle_status": "seeking",
        },
    )
    image_path = _frame_image(tmp_path / "frame.jpg")
    _write_observation(
        state_root=state_root,
        session_id="sess_tracking",
        frame_id="frame_000001",
        image_path=image_path,
        detections=[RobotDetection(track_id=15, bbox=[10, 12, 36, 44], score=0.95)],
    )

    trigger = derive_continuous_trigger(sessions.load("sess_tracking"))

    assert trigger is None


def test_derive_continuous_trigger_reuses_latest_request_id(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tracking",
        device_id="robot_01",
        text="请继续跟踪",
        request_id="req_chat_latest",
    )
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking",
        patch={
            "latest_target_id": 15,
            "next_tracking_turn_at": 0.0,
            "last_completed_frame_id": "",
            "lifecycle_status": "bound",
        },
    )
    image_path = _frame_image(tmp_path / "frame.jpg")
    _write_observation(
        state_root=state_root,
        session_id="sess_tracking",
        frame_id="frame_000001",
        image_path=image_path,
        detections=[RobotDetection(track_id=15, bbox=[10, 12, 36, 44], score=0.95)],
    )

    trigger = derive_continuous_trigger(sessions.load("sess_tracking"))

    assert trigger is not None
    assert trigger.request_id == "req_chat_latest"
