from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from world.perception import LocalPerceptionService, RobotDetection, RobotFrame, RobotIngestEvent
from agent.session import AgentSessionStore
from capabilities.tracking.agent import Re, run_tracking_agent_turn
from capabilities.tracking.effects import PENDING_REWRITE_INPUT_KEY
from capabilities.tracking.loop import supervisor_tracking_step
from capabilities.tracking.select import _select_with_model, execute_select_tool
from capabilities.tracking.types import TRIGGER_CADENCE_REVIEW, TrackingTrigger


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def _tracking_context(*, image_path: Path, latest_target_id: int | None) -> dict:
    return {
        "session_id": "sess_tracking",
        "target_description": "请跟踪穿黑衣服的人",
        "memory": {
            "core": "黑色上衣，浅色裤子，白色鞋底。",
            "front_view": "",
            "back_view": "",
            "distinguish": "",
        },
        "latest_target_id": latest_target_id,
        "front_crop_path": None,
        "back_crop_path": None,
        "frames": [
            {
                "frame_id": "frame_000001",
                "timestamp_ms": 1710000000000,
                "image_path": str(image_path),
                "detections": [
                    {
                        "track_id": 15,
                        "bounding_box_id": 15,
                        "bbox": [10, 12, 36, 44],
                        "score": 0.95,
                        "label": "person",
                    }
                ],
            }
        ],
    }


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


def test_execute_select_tool_uses_flash_for_init_and_track(tmp_path: Path, monkeypatch) -> None:
    image_path = _frame_image(tmp_path / "frame.jpg")
    init_context = _tracking_context(image_path=image_path, latest_target_id=None)
    track_context = _tracking_context(image_path=image_path, latest_target_id=15)
    requested_models: list[str] = []

    monkeypatch.setattr(
        "capabilities.tracking.select.load_settings",
        lambda _env_file: SimpleNamespace(
            api_key="test-key",
            base_url="https://example.com",
            timeout_seconds=10,
            model="qwen3.5-plus",
            main_model="qwen3.5-plus",
            sub_model="qwen3.5-plus",
            chat_model="qwen3.5-plus",
        ),
    )

    def _fake_select_with_model(**kwargs):
        requested_models.append(str(kwargs["model_name"]))
        return (
            {
                "found": True,
                "target_id": 15,
                "bounding_box_id": 15,
                "text": "已确认目标。",
                "reason": "身份特征一致。",
                "reject_reason": "",
                "needs_clarification": False,
                "clarification_question": None,
                "decision": "track",
                "candidate_checks": [],
            },
            0.01,
        )

    monkeypatch.setattr("capabilities.tracking.select._select_with_model", _fake_select_with_model)

    execute_select_tool(
        tracking_context=init_context,
        behavior="init",
        arguments={"target_description": "请跟踪穿黑衣服的人"},
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )
    execute_select_tool(
        tracking_context=track_context,
        behavior="track",
        arguments={"user_text": "继续跟踪"},
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert requested_models == ["qwen3.5-flash", "qwen3.5-flash"]


def test_select_with_model_retries_once_after_invalid_json(monkeypatch) -> None:
    responses = iter(
        [
            {"elapsed_seconds": 0.1, "response_text": '{"found": true, "bounding_box_id": 15, "decision": "track"'},
            {
                "elapsed_seconds": 0.2,
                "response_text": (
                    '{"found": true, "bounding_box_id": 15, "decision": "track", '
                    '"text": "已确认目标。", "reason": "身份特征一致。", '
                    '"reject_reason": "", "needs_clarification": false, '
                    '"clarification_question": null, "candidate_checks": []}'
                ),
            },
        ]
    )

    monkeypatch.setattr("capabilities.tracking.select.call_model", lambda **_: next(responses))

    normalized, elapsed_seconds = _select_with_model(
        settings=SimpleNamespace(api_key="test-key", base_url="https://example.com", timeout_seconds=10),
        model_name="qwen3.5-flash",
        instruction="test",
        image_paths=[],
        output_contract="{}",
        max_tokens=128,
    )

    assert normalized["decision"] == "track"
    assert normalized["target_id"] == 15
    assert elapsed_seconds == pytest.approx(0.3)


def test_supervisor_tracking_step_processes_pending_rewrite_when_idle(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tracking",
        device_id="robot_01",
        text="请继续跟踪",
        request_id="req_track",
    )
    image_path = _frame_image(tmp_path / "frame.jpg")
    _write_observation(state_root=state_root, session_id="sess_tracking", image_path=image_path)
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking",
        patch={
            "latest_target_id": 15,
            "last_completed_frame_id": "frame_000001",
            "lifecycle_status": "bound",
            PENDING_REWRITE_INPUT_KEY: {
                "task": "update",
                "crop_path": str(image_path),
                "frame_paths": [str(image_path)],
                "frame_id": "frame_000001",
                "target_id": 15,
                "request_id": "req_track",
            },
            "pending_rewrite_request_id": "req_track",
        },
    )

    monkeypatch.setattr(
        "capabilities.tracking.effects.execute_rewrite_memory_tool",
        lambda **_: {
            "task": "update",
            "memory": {
                "core": "黑色上衣，白色鞋底。",
                "front_view": "",
                "back_view": "",
                "distinguish": "",
            },
            "crop_path": str(image_path),
            "reference_view": "front",
        },
    )

    payload = supervisor_tracking_step(
        sessions=sessions,
        session_id="sess_tracking",
        device_id="robot_01",
        env_file=tmp_path / ".ENV",
        artifacts_root=artifacts_root,
        owner_id="tracking-supervisor:test",
    )

    assert payload["status"] == "rewrite_processed"
    assert payload["trigger"] == "background_rewrite"
    assert sessions.load("sess_tracking").capabilities["tracking"].get(PENDING_REWRITE_INPUT_KEY) is None
