from pathlib import Path

from scaffold.cli.run_host_agent import (
    ToolRequest,
    build_session_events_url,
    is_explicit_init_text,
    is_reset_context_text,
    latest_user_text,
    process_session,
    reconnect_delay_seconds,
    select_tool_request,
    session_ids_from_event,
    session_needs_processing,
)


def test_latest_user_text_returns_most_recent_user_message() -> None:
    raw_session = {
        "conversation_history": [
            {"role": "user", "text": "跟踪黑衣服的人"},
            {"role": "assistant", "text": "好的"},
            {"role": "user", "text": "持续跟踪"},
        ]
    }

    assert latest_user_text(raw_session) == "持续跟踪"


def test_build_session_events_url_converts_http_base_url() -> None:
    assert build_session_events_url("http://127.0.0.1:8001") == "ws://127.0.0.1:8001/ws/session-events"
    assert build_session_events_url("https://example.com/base/") == "wss://example.com/base/ws/session-events"


def test_reconnect_delay_seconds_prefers_explicit_reconnect_value() -> None:
    class Args:
        reconnect_seconds = 5.0
        poll_seconds = 2.0

    assert reconnect_delay_seconds(Args()) == 5.0


def test_session_ids_from_snapshot_event_returns_all_sessions() -> None:
    event = {
        "type": "dashboard_state",
        "sessions": [
            {"session_id": "sess_001"},
            {"session_id": "sess_002"},
        ],
    }

    assert session_ids_from_event(event, selected_session_id=None) == ["sess_001", "sess_002"]


def test_session_ids_from_update_event_filters_selected_session() -> None:
    event = {
        "type": "session_update",
        "changed_session_id": "sess_002",
    }

    assert session_ids_from_event(event, selected_session_id="sess_001") == []
    assert session_ids_from_event(event, selected_session_id="sess_002") == ["sess_002"]


def test_session_needs_processing_skips_already_handled_frame() -> None:
    raw_session = {
        "recent_frames": [{"frame_id": "frame_000001"}],
        "latest_result": {"frame_id": "frame_000001"},
    }

    assert not session_needs_processing(raw_session)


def test_select_tool_request_uses_init_for_unbound_session() -> None:
    raw_session = {
        "recent_frames": [{"frame_id": "frame_000000"}],
        "latest_result": None,
        "latest_target_id": None,
        "latest_confirmed_frame_path": None,
        "target_description": "",
        "pending_question": None,
        "conversation_history": [{"role": "user", "text": "跟踪穿黑衣服的人"}],
    }

    assert select_tool_request(raw_session, ongoing_text="持续跟踪") == ToolRequest(
        tool_name="init",
        arguments={"target_description": "跟踪穿黑衣服的人"},
    )


def test_select_tool_request_uses_track_for_active_session() -> None:
    raw_session = {
        "recent_frames": [{"frame_id": "frame_000002"}],
        "latest_result": {"frame_id": "frame_000001"},
        "latest_target_id": 7,
        "latest_confirmed_frame_path": "/tmp/frame_000001.jpg",
        "target_description": "黑衣服的人",
        "pending_question": None,
        "conversation_history": [{"role": "user", "text": "持续跟踪"}],
    }

    assert select_tool_request(raw_session, ongoing_text="持续跟踪") == ToolRequest(
        tool_name="track",
        arguments={"user_text": "持续跟踪"},
    )


def test_select_tool_request_uses_reply_for_chat_request() -> None:
    raw_session = {
        "latest_request_id": "req_chat_001",
        "latest_request_function": "chat",
        "latest_result": None,
        "recent_frames": [],
        "pending_question": None,
        "conversation_history": [{"role": "user", "text": "你是谁"}],
    }

    assert select_tool_request(raw_session, ongoing_text="持续跟踪") == ToolRequest(
        tool_name="reply",
        arguments={"question": "你是谁"},
    )


def test_is_explicit_init_text_detects_target_replacement_message() -> None:
    assert is_explicit_init_text("跟踪穿红衣服的人", ongoing_text="持续跟踪") is True
    assert is_explicit_init_text("持续跟踪", ongoing_text="持续跟踪") is False


def test_is_reset_context_text_detects_reset_commands() -> None:
    assert is_reset_context_text("clear context") is True
    assert is_reset_context_text("重置上下文") is True
    assert is_reset_context_text("持续跟踪") is False


def test_select_tool_request_uses_init_when_active_session_gets_new_target_description() -> None:
    raw_session = {
        "recent_frames": [{"frame_id": "frame_000003"}],
        "latest_result": {"frame_id": "frame_000002"},
        "latest_target_id": 7,
        "latest_confirmed_frame_path": "/tmp/frame_000002.jpg",
        "target_description": "黑衣服的人",
        "pending_question": None,
        "conversation_history": [{"role": "user", "text": "跟踪穿红衣服的人"}],
    }

    assert select_tool_request(raw_session, ongoing_text="持续跟踪") == ToolRequest(
        tool_name="init",
        arguments={"target_description": "跟踪穿红衣服的人"},
    )


def test_select_tool_request_repeats_pending_question_during_clarification() -> None:
    raw_session = {
        "recent_frames": [{"frame_id": "frame_000003"}],
        "latest_result": {"frame_id": "frame_000002"},
        "latest_target_id": None,
        "latest_confirmed_frame_path": None,
        "target_description": "黑衣服的人",
        "pending_question": "请说明是左边还是右边的人？",
        "conversation_history": [{"role": "user", "text": "持续跟踪"}],
    }

    assert select_tool_request(raw_session, ongoing_text="持续跟踪") == ToolRequest(
        tool_name="reply",
        arguments={
            "text": "请说明是左边还是右边的人？",
            "needs_clarification": True,
            "clarification_question": "请说明是左边还是右边的人？",
        },
    )


def test_select_tool_request_uses_reset_context_for_clear_context_command() -> None:
    raw_session = {
        "recent_frames": [{"frame_id": "frame_000003"}],
        "latest_result": {"frame_id": "frame_000002", "behavior": "track"},
        "latest_target_id": 7,
        "latest_confirmed_frame_path": "/tmp/frame_000002.jpg",
        "target_description": "黑衣服的人",
        "pending_question": None,
        "conversation_history": [{"role": "user", "text": "clear context"}],
    }

    assert select_tool_request(raw_session, ongoing_text="持续跟踪") == ToolRequest(
        tool_name="reset_context",
        arguments={},
    )


def test_process_session_calls_bridge_for_pending_frame(monkeypatch, tmp_path: Path) -> None:
    raw_session = {
        "session_id": "sess_001",
        "recent_frames": [{"frame_id": "frame_000001"}],
        "latest_result": None,
        "latest_target_id": None,
        "latest_confirmed_frame_path": None,
        "target_description": "",
        "pending_question": None,
        "conversation_history": [{"role": "user", "text": "跟踪黑衣服的人"}],
    }
    calls = []

    monkeypatch.setattr(
        "scaffold.cli.run_host_agent.bridge.fetch_json",
        lambda url: raw_session,
    )

    def fake_run_bridge(**kwargs):
        calls.append(kwargs)
        return {
            "tool_output": {
                "found": True,
                "needs_clarification": False,
                "text": "已确认目标。",
            }
        }

    monkeypatch.setattr("scaffold.cli.run_host_agent.bridge.run_bridge", fake_run_bridge)

    result = process_session(
        backend_base_url="http://127.0.0.1:8001",
        session_id="sess_001",
        ongoing_text="持续跟踪",
        env_file=tmp_path / ".ENV",
        config_path=tmp_path / "config.json",
        artifacts_root=tmp_path / "artifacts",
        skip_rewrite_memory=False,
    )

    assert result["status"] == "processed"
    assert result["tool"] == "init"
    assert calls[0]["tool_name"] == "init"
    assert calls[0]["arguments"] == {"target_description": "跟踪黑衣服的人"}


def test_process_session_returns_idle_when_frame_is_already_handled(monkeypatch, tmp_path: Path) -> None:
    raw_session = {
        "session_id": "sess_001",
        "recent_frames": [{"frame_id": "frame_000001"}],
        "latest_result": {"frame_id": "frame_000001"},
        "conversation_history": [{"role": "user", "text": "持续跟踪"}],
    }

    monkeypatch.setattr(
        "scaffold.cli.run_host_agent.bridge.fetch_json",
        lambda url: raw_session,
    )

    result = process_session(
        backend_base_url="http://127.0.0.1:8001",
        session_id="sess_001",
        ongoing_text="持续跟踪",
        env_file=tmp_path / ".ENV",
        config_path=tmp_path / "config.json",
        artifacts_root=tmp_path / "artifacts",
        skip_rewrite_memory=False,
    )

    assert result == {
        "session_id": "sess_001",
        "frame_id": "frame_000001",
        "status": "idle",
    }


def test_process_session_posts_reset_context_for_clear_context_command(monkeypatch, tmp_path: Path) -> None:
    raw_session = {
        "session_id": "sess_001",
        "recent_frames": [{"frame_id": "frame_000001"}],
        "latest_result": {"frame_id": "frame_000001", "behavior": "track"},
        "latest_target_id": 12,
        "latest_confirmed_frame_path": "/tmp/frame_000001.jpg",
        "target_description": "黑衣服的人",
        "pending_question": None,
        "conversation_history": [{"role": "user", "text": "clear context"}],
    }
    calls = []

    monkeypatch.setattr(
        "scaffold.cli.run_host_agent.bridge.fetch_json",
        lambda url: raw_session,
    )
    monkeypatch.setattr(
        "scaffold.cli.run_host_agent.bridge.post_json",
        lambda url, payload: calls.append((url, payload)) or {
            "latest_result": {"text": "Tracking context cleared."}
        },
    )

    result = process_session(
        backend_base_url="http://127.0.0.1:8001",
        session_id="sess_001",
        ongoing_text="持续跟踪",
        env_file=tmp_path / ".ENV",
        config_path=tmp_path / "config.json",
        artifacts_root=tmp_path / "artifacts",
        skip_rewrite_memory=False,
    )

    assert calls == [("http://127.0.0.1:8001/api/v1/sessions/sess_001/reset-context", {})]
    assert result["status"] == "processed"
    assert result["tool"] == "reset_context"
    assert result["text"] == "Tracking context cleared."
