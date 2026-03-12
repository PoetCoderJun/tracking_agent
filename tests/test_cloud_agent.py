from __future__ import annotations

from pathlib import Path

from tracking_agent.backend_store import BackendDetection, BackendFrame, BackendSession
from tracking_agent.cloud_agent import (
    CloudTrackingAgent,
    normalize_orchestration_result,
    normalize_select_result,
    session_has_active_target,
    should_force_init,
)
from tracking_agent.config import Settings


def _session(latest_target_id=None, latest_memory="") -> BackendSession:
    return BackendSession(
        session_id="sess_001",
        device_id="robot_01",
        target_description="黑衣服的人",
        latest_memory=latest_memory,
        latest_target_id=latest_target_id,
        latest_target_crop=None,
        latest_confirmed_frame_path=None,
        latest_result=None,
        result_history=[],
        clarification_notes=[],
        conversation_history=[],
        pending_question=None,
        recent_frames=[],
        created_at="2026-03-12T00:00:00+00:00",
        updated_at="2026-03-12T00:00:00+00:00",
    )


def test_normalize_orchestration_result_accepts_supported_actions() -> None:
    normalized = normalize_orchestration_result(
        {
            "action": "track",
            "reply": "",
            "target_description": "",
            "pending_question": None,
            "reason": "session active",
        }
    )
    assert normalized["action"] == "track"


def test_normalize_orchestration_result_rejects_unknown_actions() -> None:
    try:
        normalize_orchestration_result({"action": "chat"})
    except ValueError as exc:
        assert "Unsupported orchestrator action" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected normalize_orchestration_result to reject unknown action")


def test_normalize_select_result_backfills_clarification_question() -> None:
    normalized = normalize_select_result(
        {
            "found": False,
            "target_id": None,
            "reason": "有多个候选人",
            "needs_clarification": True,
        }
    )

    assert normalized["found"] is False
    assert normalized["clarification_question"]
    assert normalized["text"] == "有多个候选人"


def test_normalize_select_result_accepts_bounding_box_id_alias() -> None:
    normalized = normalize_select_result(
        {
            "found": True,
            "bounding_box_id": 15,
            "text": "已确认目标。",
            "reason": "",
            "needs_clarification": False,
        }
    )

    assert normalized["found"] is True
    assert normalized["target_id"] == 15
    assert normalized["bounding_box_id"] == 15


def test_should_force_init_for_new_target_description_without_active_target() -> None:
    session = _session(latest_target_id=None, latest_memory="")

    assert session_has_active_target(session) is False
    assert should_force_init(session, "跟踪穿黑衣服的人") is True


def test_should_not_force_init_for_generic_continuation_text() -> None:
    session = _session(latest_target_id=None, latest_memory="")

    assert should_force_init(session, "持续跟踪") is False


def test_should_not_force_init_for_non_target_question_without_pending_prompt() -> None:
    session = _session(latest_target_id=None, latest_memory="")

    assert should_force_init(session, "现在状态如何") is False


def test_should_force_init_for_clarification_answer_without_active_target() -> None:
    session = BackendSession(
        session_id="sess_001",
        device_id="robot_01",
        target_description="黑衣服的人",
        latest_memory="",
        latest_target_id=None,
        latest_target_crop=None,
        latest_confirmed_frame_path=None,
        latest_result=None,
        result_history=[],
        clarification_notes=[],
        conversation_history=[],
        pending_question="请再具体描述一下要跟踪的人。",
        recent_frames=[],
        created_at="2026-03-12T00:00:00+00:00",
        updated_at="2026-03-12T00:00:00+00:00",
    )

    assert should_force_init(session, "左边穿黑衣服的人") is True


def test_session_has_active_target_requires_id_and_confirmed_frame() -> None:
    session = BackendSession(
        session_id="sess_001",
        device_id="robot_01",
        target_description="黑衣服的人",
        latest_memory="",
        latest_target_id=1,
        latest_target_crop=None,
        latest_confirmed_frame_path=str(Path("/tmp/frame.jpg")),
        latest_result=None,
        result_history=[],
        clarification_notes=[],
        conversation_history=[],
        pending_question=None,
        recent_frames=[],
        created_at="2026-03-12T00:00:00+00:00",
        updated_at="2026-03-12T00:00:00+00:00",
    )

    assert session_has_active_target(session) is True


def test_run_select_defers_memory_rewrite_to_background_worker(tmp_path: Path, monkeypatch) -> None:
    frame_path = tmp_path / "frame_000001.jpg"
    frame_path.write_bytes(b"frame")

    def fake_settings(_: Path) -> Settings:
        return Settings(
            api_key="",
            base_url="http://example.test",
            model="main",
            main_model="main",
            sub_model="sub",
            timeout_seconds=30,
            sample_fps=1.0,
            query_interval_seconds=3,
            recent_frame_count=3,
        )

    calls: list[dict[str, object]] = []

    def fake_call_model(**kwargs):
        calls.append(kwargs)
        return {
            "response_text": '{"found": true, "bounding_box_id": 15, "text": "已确认目标", "needs_clarification": false, "reason": ""}'
        }

    def fake_save_detection_visualization(image_path: Path, detections, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"overlay")

    def fake_save_target_crop(image_path: Path, bbox, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"crop")

    monkeypatch.setattr("tracking_agent.cloud_agent.load_settings", fake_settings)
    monkeypatch.setattr("tracking_agent.cloud_agent.call_model", fake_call_model)
    monkeypatch.setattr(
        "tracking_agent.cloud_agent.save_detection_visualization",
        fake_save_detection_visualization,
    )
    monkeypatch.setattr("tracking_agent.cloud_agent.save_target_crop", fake_save_target_crop)

    agent = CloudTrackingAgent(env_path=tmp_path / ".ENV")
    session = BackendSession(
        session_id="sess_001",
        device_id="robot_01",
        target_description="穿黑衣服的人",
        latest_memory="",
        latest_target_id=None,
        latest_target_crop=None,
        latest_confirmed_frame_path=None,
        latest_result=None,
        result_history=[],
        clarification_notes=[],
        conversation_history=[],
        pending_question=None,
        recent_frames=[
            BackendFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
                detections=[
                    BackendDetection(track_id=15, bbox=[10, 20, 30, 40], score=0.95),
                ],
            )
        ],
        created_at="2026-03-12T00:00:00+00:00",
        updated_at="2026-03-12T00:00:00+00:00",
    )

    result = agent._run_select(
        session=session,
        session_dir=tmp_path / "session",
        text="穿黑衣服的人",
        behavior="init",
    )

    assert len(calls) == 1
    assert result["memory"] == ""
    assert result["memory_rewrite"] is not None
    assert result["memory_rewrite"]["task"] == "init"
    assert result["memory_rewrite"]["frame_id"] == "frame_000001"
