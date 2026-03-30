from __future__ import annotations

from pathlib import Path

from PIL import Image

from backend.agent import LocalAgentRuntime
from backend.perception import RobotDetection, RobotFrame, RobotIngestEvent, build_perception_bundle


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def test_local_agent_runtime_context_contains_generic_state(tmp_path: Path) -> None:
    runtime = LocalAgentRuntime(tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    runtime.update_user_preferences("sess_001", {"language": "zh"})
    runtime.update_environment_map("sess_001", {"rooms": {"lab": {"visible": True}}})
    context = runtime.ingest_event(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
            text="跟踪穿黑衣服的人",
        ),
        request_id="req_001",
        request_function="tracking",
    )

    assert context.raw_session["latest_request_id"] == "req_001"
    assert context.user_preferences["language"] == "zh"
    assert context.environment_map["rooms"]["lab"]["visible"] is True
    assert context.perception_cache["vision"]["latest_frame_id"] == "frame_000001"
    assert context.perception_cache["language"]["latest_text"] == "跟踪穿黑衣服的人"
    assert context.state_paths["session_path"].endswith("/sessions/sess_001/session.json")
    assert context.state_paths["agent_memory_path"].endswith("/sessions/sess_001/agent_memory.json")


def test_build_perception_bundle_surfaces_memory_language_and_map(tmp_path: Path) -> None:
    runtime = LocalAgentRuntime(tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")
    runtime.update_user_preferences("sess_001", {"language": "zh"})
    runtime.update_environment_map("sess_001", {"map_id": "lab-01"})
    context = runtime.ingest_event(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[],
            text="继续跟踪",
        ),
        request_id="req_001",
        request_function="tracking",
    )

    bundle = build_perception_bundle(context)

    assert bundle.vision["latest_frame"]["frame_id"] == "frame_000001"
    assert bundle.language["latest_request_function"] == "tracking"
    assert bundle.user_preferences["language"] == "zh"
    assert bundle.environment_map["map_id"] == "lab-01"


def test_observation_ingest_updates_state_without_polluting_chat_history(tmp_path: Path) -> None:
    runtime = LocalAgentRuntime(tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    context = runtime.ingest_event(
        RobotIngestEvent(
            session_id="sess_obs",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[],
            text="camera observation",
        ),
        request_id="req_obs_001",
        request_function="observation",
    )

    assert context.raw_session["latest_request_function"] == "observation"
    assert context.raw_session["conversation_history"] == []
    assert context.perception_cache["language"]["latest_text"] == "camera observation"
