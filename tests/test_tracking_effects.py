from __future__ import annotations

from pathlib import Path

from agent.state.session import AgentSessionStore
import capabilities.tracking.runtime.effects as tracking_effects
from capabilities.tracking.runtime.effects import (
    PENDING_REWRITE_INPUT_KEY,
    apply_tracking_decision,
    drain_pending_tracking_memory_rewrite,
)
from capabilities.tracking.runtime.types import ACTION_ASK, ACTION_TRACK, TRIGGER_CHAT_INIT, TrackingDecision, TrackingTrigger
from capabilities.tracking.state.memory import read_tracking_memory_snapshot


def test_tracking_effects_remove_compat_writer_adapter() -> None:
    assert not hasattr(tracking_effects, "apply_tracking_payload_compat")


def test_apply_tracking_decision_chat_init_ask_sets_pending_question(tmp_path: Path) -> None:
    sessions = AgentSessionStore(tmp_path / "state")
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    session = sessions.load("sess_tracking")

    payload = apply_tracking_decision(
        sessions=sessions,
        session_id="sess_tracking",
        session=session,
        trigger=TrackingTrigger(
            type=TRIGGER_CHAT_INIT,
            cause="new_user_target",
            frame_id=None,
            request_id="req_init",
            requested_text="请跟踪穿黑衣服的人",
            source="tracking_init_skill",
        ),
        decision=TrackingDecision(
            action=ACTION_ASK,
            frame_id=None,
            target_id=None,
            text="当前无法确认目标，请补充描述。",
            reason="证据不足。",
            question="当前无法确认目标，请补充描述。",
            target_description="请跟踪穿黑衣服的人",
        ),
        env_file=tmp_path / ".ENV",
    )
    session = sessions.load("sess_tracking")

    assert payload["skill_state_patch"]["pending_question"] == "当前无法确认目标，请补充描述。"
    assert session.capabilities["tracking-init"]["pending_question"] == "当前无法确认目标，请补充描述。"
    assert session.capabilities["tracking-init"]["target_description"] == "请跟踪穿黑衣服的人"


def test_apply_tracking_decision_track_with_memory_effect_enqueues_background_rewrite(tmp_path: Path, monkeypatch) -> None:
    sessions = AgentSessionStore(tmp_path / "state")
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    session = sessions.load("sess_tracking")
    crop_path = tmp_path / "crop.jpg"
    crop_path.write_bytes(b"fake")

    monkeypatch.setattr(
        "capabilities.tracking.runtime.effects.execute_rewrite_memory_tool",
        lambda **_: {
            "task": "init",
            "memory": {
                "core": "黑色上衣，白色鞋底。",
                "front_view": "正面黑上衣。",
                "back_view": "",
                "distinguish": "",
            },
            "crop_path": str(crop_path),
            "reference_view": "front",
        },
    )

    payload = apply_tracking_decision(
        sessions=sessions,
        session_id="sess_tracking",
        session=session,
        trigger=TrackingTrigger(
            type=TRIGGER_CHAT_INIT,
            cause="new_user_target",
            frame_id="frame_000001",
            request_id="req_init",
            requested_text="请跟踪穿黑衣服的人",
            source="tracking_init_skill",
        ),
        decision=TrackingDecision(
            action=ACTION_TRACK,
            frame_id="frame_000001",
            target_id=15,
            text="已确认目标。",
            reason="身份特征一致。",
            target_description="请跟踪穿黑衣服的人",
            memory_effect={"rewrite_input": {"task": "init", "crop_path": str(crop_path), "frame_paths": [str(crop_path)], "frame_id": "frame_000001", "target_id": 15}},
        ),
        env_file=tmp_path / ".ENV",
    )
    memory_snapshot = read_tracking_memory_snapshot(state_root=tmp_path / "state", session_id="sess_tracking")
    session = sessions.load("sess_tracking")

    assert "rewrite_output" not in payload
    assert payload["rewrite_memory_input"]["target_id"] == 15
    assert memory_snapshot["memory"]["core"] == ""
    assert payload["session_result"]["text"] == session.latest_result["text"]
    assert session.conversation_history[-1]["text"] == session.latest_result["text"]
    assert session.capabilities["tracking-init"]["latest_target_id"] == 15
    assert session.capabilities["tracking-init"][PENDING_REWRITE_INPUT_KEY]["target_id"] == 15


def test_drain_pending_tracking_memory_rewrite_writes_memory_and_clears_queue(tmp_path: Path, monkeypatch) -> None:
    sessions = AgentSessionStore(tmp_path / "state")
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tracking",
        device_id="robot_01",
        text="初始请求",
        request_id="req_init",
    )
    crop_path = tmp_path / "crop.jpg"
    crop_path.write_bytes(b"fake")

    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking-init",
        patch={
            "latest_target_id": 15,
            PENDING_REWRITE_INPUT_KEY: {
                "task": "init",
                "crop_path": str(crop_path),
                "frame_paths": [str(crop_path)],
                "frame_id": "frame_000001",
                "target_id": 15,
                "request_id": "req_init",
            },
            "pending_rewrite_request_id": "req_init",
        },
    )

    monkeypatch.setattr(
        "capabilities.tracking.runtime.effects.execute_rewrite_memory_tool",
        lambda **_: {
            "task": "init",
            "memory": {
                "core": "黑色上衣，白色鞋底。",
                "front_view": "正面黑上衣。",
                "back_view": "",
                "distinguish": "",
            },
            "crop_path": str(crop_path),
            "reference_view": "front",
        },
    )

    payload = drain_pending_tracking_memory_rewrite(
        sessions=sessions,
        session_id="sess_tracking",
        env_file=tmp_path / ".ENV",
    )

    memory_snapshot = read_tracking_memory_snapshot(state_root=tmp_path / "state", session_id="sess_tracking")
    session = sessions.load("sess_tracking")

    assert payload["status"] == "processed"
    assert memory_snapshot["memory"]["core"] == "黑色上衣，白色鞋底。"
    assert session.capabilities["tracking-init"].get(PENDING_REWRITE_INPUT_KEY) is None
def test_apply_tracking_decision_drops_stale_request_without_mutating_tracking_state(tmp_path: Path) -> None:
    sessions = AgentSessionStore(tmp_path / "state")
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tracking",
        device_id="robot_01",
        text="旧请求",
        request_id="req_old",
    )
    stale_session = sessions.load("sess_tracking")
    sessions.append_chat_request(
        session_id="sess_tracking",
        device_id="robot_01",
        text="新请求",
        request_id="req_new",
    )

    payload = apply_tracking_decision(
        sessions=sessions,
        session_id="sess_tracking",
        session=stale_session,
        trigger=TrackingTrigger(
            type="cadence_review",
            cause="due_interval",
            frame_id="frame_000001",
            request_id="req_old",
            requested_text="",
            source="tracking_loop",
        ),
        decision=TrackingDecision(
            action=ACTION_TRACK,
            frame_id="frame_000001",
            target_id=15,
            text="继续跟踪。",
            reason="旧请求不应提交。",
        ),
        env_file=tmp_path / ".ENV",
    )
    session = sessions.load("sess_tracking")

    assert payload["status"] == "dropped"
    assert session.latest_result is None
    assert session.capabilities == {}


def test_drain_pending_tracking_memory_rewrite_drops_stale_request(tmp_path: Path, monkeypatch) -> None:
    sessions = AgentSessionStore(tmp_path / "state")
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tracking",
        device_id="robot_01",
        text="初始请求",
        request_id="req_init",
    )
    crop_path = tmp_path / "crop.jpg"
    crop_path.write_bytes(b"fake")
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking-init",
        patch={
            "latest_target_id": 15,
            PENDING_REWRITE_INPUT_KEY: {
                "task": "init",
                "crop_path": str(crop_path),
                "frame_paths": [str(crop_path)],
                "frame_id": "frame_000001",
                "target_id": 15,
                "request_id": "req_init",
            },
            "pending_rewrite_request_id": "req_init",
        },
    )
    sessions.append_chat_request(
        session_id="sess_tracking",
        device_id="robot_01",
        text="更晚的新请求",
        request_id="req_newer",
    )
    monkeypatch.setattr(
        "capabilities.tracking.runtime.effects.execute_rewrite_memory_tool",
        lambda **_: {
            "task": "init",
            "memory": {
                "core": "不应被写入",
                "front_view": "",
                "back_view": "",
                "distinguish": "",
            },
            "crop_path": str(crop_path),
            "reference_view": "front",
        },
    )

    payload = drain_pending_tracking_memory_rewrite(
        sessions=sessions,
        session_id="sess_tracking",
        env_file=tmp_path / ".ENV",
    )
    memory_snapshot = read_tracking_memory_snapshot(state_root=tmp_path / "state", session_id="sess_tracking")
    final_session = sessions.load("sess_tracking")

    assert payload["status"] == "dropped"
    assert final_session.session["latest_request_id"] == "req_newer"
    assert memory_snapshot["memory"]["core"] == ""
    assert final_session.capabilities["tracking-init"].get(PENDING_REWRITE_INPUT_KEY) is None
