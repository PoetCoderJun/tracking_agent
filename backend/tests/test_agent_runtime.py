from __future__ import annotations

from pathlib import Path

from PIL import Image

from backend.runtime_session import AgentSessionStore
from backend.perception import (
    LocalPerceptionService,
    RobotDetection,
    RobotFrame,
    RobotIngestEvent,
    build_perception_bundle,
)


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def test_agent_session_store_load_contains_generic_state(tmp_path: Path) -> None:
    runtime = AgentSessionStore(tmp_path / "state")
    perception = LocalPerceptionService(tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    runtime.patch_user_preferences("sess_001", {"language": "zh"})
    runtime.patch_environment("sess_001", {"rooms": {"lab": {"visible": True}}})
    perception.write_observation(
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
    )
    context = runtime.load("sess_001", device_id="robot_01")

    assert context.user_preferences["language"] == "zh"
    assert context.environment["rooms"]["lab"]["visible"] is True
    assert context.session["conversation_history"] == []
    assert context.state_paths["session_path"].endswith("/sessions/sess_001/session.json")
    assert context.state_paths["session_path"].endswith("/sessions/sess_001/session.json")


def test_agent_session_store_builds_perception_bundle(tmp_path: Path) -> None:
    runtime = AgentSessionStore(tmp_path / "state")
    perception = LocalPerceptionService(tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")
    runtime.patch_user_preferences("sess_001", {"language": "zh"})
    runtime.patch_environment("sess_001", {"map_id": "lab-01"})
    perception.write_observation(
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
    )
    context = runtime.load("sess_001", device_id="robot_01")

    bundle = build_perception_bundle(context)

    assert bundle.vision["latest_frame"]["frame_id"] == "frame_000001"
    assert bundle.system1["latest_frame_result"] is None
    assert bundle.system1["recent_frame_results"] == []
    assert bundle.language["latest_request_function"] is None
    assert bundle.user_preferences["language"] == "zh"
    assert bundle.environment_map["map_id"] == "lab-01"


def test_agent_session_store_builds_system1_bundle(tmp_path: Path) -> None:
    runtime = AgentSessionStore(tmp_path / "state")
    perception = LocalPerceptionService(tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")
    perception.write_observation(
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
    )
    perception.write_frame_result(
        {
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_path": str(frame_path),
            "detections": [
                {
                    "track_id": 12,
                    "bbox": [10, 20, 30, 40],
                    "score": 0.95,
                    "label": "person",
                }
            ],
        }
    )

    bundle = build_perception_bundle(runtime.load("sess_001", device_id="robot_01"))

    assert bundle.system1["latest_frame_result"]["frame_id"] == "frame_000001"
    assert bundle.system1["recent_frame_results"][0]["detections"][0]["track_id"] == 12


def test_agent_session_store_observation_ingest_does_not_pollute_chat_history(tmp_path: Path) -> None:
    runtime = AgentSessionStore(tmp_path / "state")
    perception = LocalPerceptionService(tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    perception.write_observation(
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
    )
    context = runtime.load("sess_obs", device_id="robot_01")

    assert context.session["latest_request_function"] is None
    assert context.session["conversation_history"] == []


def test_agent_session_store_apply_skill_result_keeps_runtime_summary_small(tmp_path: Path) -> None:
    runtime = AgentSessionStore(tmp_path / "state")
    perception = LocalPerceptionService(tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")
    runtime.start_fresh_session("sess_result", device_id="robot_01")

    perception.write_observation(
        RobotIngestEvent(
            session_id="sess_result",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[],
            text="继续跟踪",
        ),
    )

    context = runtime.apply_skill_result(
        "sess_result",
        {
            "behavior": "track",
            "frame_id": "frame_000001",
            "target_id": 12,
            "found": True,
            "decision": "track",
            "text": "已确认继续跟踪 ID 12。",
            "latest_result": {"should_not": "persist"},
        },
    )

    runtime_state = context.runtime_summary
    assert runtime_state["has_latest_result"] is True
    assert runtime_state["latest_behavior"] == "track"
    assert runtime_state["latest_frame_id"] == "frame_000001"
    assert runtime_state["latest_target_id"] == 12
    assert runtime_state["latest_found"] is True
    assert runtime_state["latest_decision"] == "track"
    assert runtime_state["latest_text"] == "已确认继续跟踪 ID 12。"
    assert "latest_result" not in runtime_state


def test_agent_session_exposes_canonical_language_context(tmp_path: Path) -> None:
    runtime = AgentSessionStore(tmp_path / "state")
    runtime.start_fresh_session("sess_lang", device_id="robot_01")
    runtime.append_chat_request(
        session_id="sess_lang",
        device_id="robot_01",
        text="先看左边的人",
        request_id="req_001",
    )
    runtime.apply_skill_result(
        "sess_lang",
        {
            "request_id": "req_001",
            "function": "chat",
            "behavior": "reply",
            "text": "收到，先观察左边。",
        },
    )
    context = runtime.load("sess_lang", device_id="robot_01")

    assert context.latest_user_text == "先看左边的人"
    assert context.language_context["latest_request_function"] == "chat"
    assert context.language_context["latest_user_text"] == "先看左边的人"
    assert context.language_context["recent_dialogue"][-1]["text"] == "收到，先观察左边。"
