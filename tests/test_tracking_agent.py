from __future__ import annotations

from pathlib import Path

from PIL import Image

from world.perception import LocalPerceptionService, RobotDetection, RobotFrame, RobotIngestEvent
from agent.session import AgentSessionStore
from capabilities.tracking.agent import Re, run_tracking_agent_turn
from capabilities.tracking.types import TRIGGER_CADENCE_REVIEW, TrackingTrigger


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def _write_observation(*, state_root: Path, session_id: str, image_path: Path) -> None:
    perception = LocalPerceptionService(state_root)
    perception.write_observation(
        RobotIngestEvent(
            session_id=session_id,
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(image_path),
            ),
            detections=[RobotDetection(track_id=15, bbox=[10, 12, 36, 44], score=0.95)],
            text="tracking",
        )
    )


def test_re_exposes_observation_without_dialogue(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tracking",
        device_id="robot_01",
        text="这段对话不该进入 continuous observation",
        request_id="req_001",
    )
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking",
        patch={"latest_target_id": 15, "lifecycle_status": "bound"},
    )
    image_path = _frame_image(tmp_path / "frame.jpg")
    _write_observation(state_root=state_root, session_id="sess_tracking", image_path=image_path)

    observation = Re(
        session=sessions.load("sess_tracking"),
        trigger=TrackingTrigger(
            type=TRIGGER_CADENCE_REVIEW,
            cause="due_interval",
            frame_id="frame_000001",
            request_id="req_track",
            requested_text="",
            source="tracking_loop",
        ),
    )

    assert observation.latest_frame["frame_id"] == "frame_000001"
    assert not hasattr(observation, "chat_history")


def test_run_tracking_agent_turn_keeps_top_level_flow_and_commits_result(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking",
        patch={"latest_target_id": 15, "lifecycle_status": "bound"},
    )
    image_path = _frame_image(tmp_path / "frame.jpg")
    _write_observation(state_root=state_root, session_id="sess_tracking", image_path=image_path)

    monkeypatch.setattr(
        "capabilities.tracking.agent.execute_select_tool",
        lambda **_: {
            "behavior": "track",
            "frame_id": "frame_000001",
            "target_id": 15,
            "bounding_box_id": 15,
            "found": True,
            "decision": "track",
            "text": "继续跟踪当前目标。",
            "reason": "当前候选和 tracking memory 一致。",
            "candidate_checks": [],
        },
    )

    payload = run_tracking_agent_turn(
        sessions=sessions,
        session_id="sess_tracking",
        session=sessions.load("sess_tracking"),
        trigger=TrackingTrigger(
            type=TRIGGER_CADENCE_REVIEW,
            cause="due_interval",
            frame_id="frame_000001",
            request_id="req_track",
            requested_text="",
            source="tracking_loop",
        ),
        env_file=tmp_path / ".ENV",
        artifacts_root=artifacts_root,
    )
    session = sessions.load("sess_tracking")

    assert payload["status"] == "processed"
    assert session.latest_result["text"] == "继续跟踪当前目标。"
    assert session.capabilities["tracking"]["last_reviewed_trigger"] == TRIGGER_CADENCE_REVIEW
