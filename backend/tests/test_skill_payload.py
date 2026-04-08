from __future__ import annotations

from pathlib import Path

from backend.runtime_apply import apply_processed_payload
from backend.runtime_session import AgentSessionStore
from backend.skill_payload import processed_skill_payload, reply_session_result


def test_processed_skill_payload_omits_unused_optional_fields() -> None:
    payload = processed_skill_payload(
        skill_name="describe_image",
        session_result=reply_session_result("我看到一名站着的人。"),
        tool="describe_image",
        tool_output={"image_path": "/tmp/frame.jpg"},
    )

    assert payload["status"] == "processed"
    assert payload["skill_name"] == "describe_image"
    assert payload["tool"] == "describe_image"
    assert payload["tool_output"] == {"image_path": "/tmp/frame.jpg"}
    assert "latest_result_patch" not in payload
    assert "skill_state_patch" not in payload
    assert "user_preferences_patch" not in payload
    assert "environment_map_patch" not in payload
    assert "perception_cache_patch" not in payload
    assert "rewrite_output" not in payload
    assert "rewrite_memory_input" not in payload
    assert "robot_response" not in payload


def test_apply_processed_payload_returns_compact_response(tmp_path: Path) -> None:
    sessions = AgentSessionStore(tmp_path / "state")
    sessions.start_fresh_session("sess_001", device_id="robot_01")

    payload = processed_skill_payload(
        skill_name="describe_image",
        session_result=reply_session_result("我看到一名站着的人。"),
        tool="describe_image",
        tool_output={"image_path": "/tmp/frame.jpg"},
    )
    applied = apply_processed_payload(
        sessions=sessions,
        session_id="sess_001",
        pi_payload=payload,
        env_file=tmp_path / ".ENV",
    )

    assert applied["status"] == "processed"
    assert applied["skill_name"] == "describe_image"
    assert applied["tool"] == "describe_image"
    assert applied["tool_output"] == {"image_path": "/tmp/frame.jpg"}
    assert applied["robot_response"]["action"] == "reply"
    assert applied["session_result"]["text"] == "我看到一名站着的人。"
    assert "latest_result_patch" not in applied
    assert "skill_state_patch" not in applied
    assert "user_preferences_patch" not in applied
    assert "environment_map_patch" not in applied
    assert "perception_cache_patch" not in applied
    assert "rewrite_output" not in applied
    assert "rewrite_memory_input" not in applied
