from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import scripts.e_agent as e_agent

from agent.runner import commit_skill_turn, run_ordinary_skill_turn
from agent.session import AgentSessionStore
from agent.skill_payload import processed_skill_payload, reply_session_result
import capabilities.tracking.deterministic as tracking_deterministic
from capabilities.tracking.deterministic import process_tracking_init_direct
import skills.feishu.scripts.notify_turn as feishu_turn
import skills.tts.scripts.speak_turn as tts_turn


ROOT = Path(__file__).resolve().parents[1]


def _load_script_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeProcess:
    def __init__(self, captured: dict[str, object], command: list[str], env: dict[str, str]) -> None:
        captured["command"] = command
        captured["env"] = env
        self._captured = captured
        self._poll_calls = 0

    def poll(self) -> int | None:
        self._poll_calls += 1
        return 0 if self._poll_calls > 1 else None

    def terminate(self) -> None:
        self._captured["terminated"] = True

    def wait(self, timeout: float | None = None) -> int:
        self._captured["wait_timeout"] = timeout
        return 0


def test_main_bootstraps_pi_runner_with_project_skills(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    state_root = tmp_path / "state"

    monkeypatch.setattr(
        e_agent.subprocess,
        "Popen",
        lambda command, env: _FakeProcess(captured, command, env),
    )
    monkeypatch.setattr(e_agent, "_sandbox_profile_path", lambda args, env: tmp_path / "pi-readonly.sb")
    monkeypatch.setattr(e_agent, "run_due_tracking_step", lambda **kwargs: {"status": "idle"})

    exit_code = e_agent.main(
        [
            "--state-root",
            str(state_root),
            "--pi-bin",
            "pi",
            "--",
            "--model",
            "gpt-5",
        ]
    )

    active_session = json.loads((state_root / "active_session.json").read_text(encoding="utf-8"))
    command = captured["command"]
    skill_args = [command[index + 1] for index, item in enumerate(command[:-1]) if item == "--skill"]
    prompt_args = [command[index + 1] for index, item in enumerate(command[:-1]) if item == "--append-system-prompt"]

    assert exit_code == 0
    assert captured["env"]["ROBOT_AGENT_SESSION_ID"] == active_session["session_id"]
    assert captured["env"]["ROBOT_AGENT_STATE_ROOT"] == str(state_root.resolve())
    assert captured["env"]["ROBOT_AGENT_TURN_OWNER_ID"] == "pi"
    assert command[0] == "pi"
    assert command[1:3] == ["--thinking", "minimal"]
    assert "--no-skills" in command
    assert "--model" in command
    assert skill_args
    assert any(path.endswith("/skills/tracking") for path in skill_args)
    assert any(path.endswith("/skills/tts") for path in skill_args)
    assert len(prompt_args) == 1
    assert "具身智能机器狗" in prompt_args[0]
    assert str((state_root / "perception" / "snapshot.json").resolve()) in prompt_args[0]
    assert "当前启动时还没有可用的 latest_frame.image_path" in prompt_args[0]


def test_vision_grounding_prompt_uses_latest_frame_path_when_available(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    snapshot_path = state_root / "perception" / "snapshot.json"
    image_path = (tmp_path / "frame.jpg").resolve()
    image_path.write_bytes(b"frame")
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "recent_camera_observations": [],
                "latest_frame": {
                    "frame_id": "frame_001",
                    "timestamp_ms": 123,
                    "image_path": str(image_path),
                    "detections": [],
                },
                "latest_camera_observation": None,
                "recent_frame_results": [],
                "latest_frame_result": None,
                "model": {},
                "saved_keyframes": [],
                "stream_status": {},
            },
            indent=2,
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    prompt = e_agent._vision_grounding_prompt(state_root=state_root)

    assert str(snapshot_path.resolve()) in prompt
    assert f"当前启动时 latest_frame.image_path={str(image_path)}" in prompt
    assert "不要把这个启动时路径当作长期真相" in prompt


def test_chat_reply_updates_main_session_dialogue(tmp_path: Path) -> None:
    sessions = AgentSessionStore(tmp_path / "state")
    sessions.start_fresh_session("sess_chat", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_chat",
        device_id="robot_01",
        text="你好",
        request_id="req_001",
    )

    sessions.apply_skill_result(
        "sess_chat",
        {
            "request_id": "req_001",
            "function": "chat",
            "behavior": "reply",
            "text": "你好，我在。",
        },
    )

    session = sessions.load("sess_chat")

    assert session.latest_user_text == "你好"
    assert session.latest_result["function"] == "chat"
    assert session.latest_result["text"] == "你好，我在。"
    assert [entry["role"] for entry in session.conversation_history] == ["user", "assistant"]
    assert session.conversation_history[-1]["text"] == "你好，我在。"


def test_chat_can_trigger_skill_for_assist_reply(tmp_path: Path) -> None:
    sessions = AgentSessionStore(tmp_path / "state")
    sessions.start_fresh_session("sess_skill", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_skill",
        device_id="robot_01",
        text="帮我查一下机器人新闻",
        request_id="req_001",
    )

    payload = processed_skill_payload(
        skill_name="web_search",
        session_result={
            "request_id": "req_001",
            "function": "chat",
            **reply_session_result("我查到两条机器人新闻，已经整理给你。"),
        },
        tool="search",
        tool_output={"query": "机器人新闻"},
        skill_state_patch={"last_query": "机器人新闻", "last_summary": "两条结果"},
    )

    applied = commit_skill_turn(
        sessions=sessions,
        session_id="sess_skill",
        pi_payload=payload,
        env_file=tmp_path / ".ENV",
    )
    session = sessions.load("sess_skill")

    assert applied["skill_name"] == "web_search"
    assert applied["tool"] == "search"
    assert session.latest_result["function"] == "chat"
    assert session.latest_result["text"] == "我查到两条机器人新闻，已经整理给你。"
    assert session.capabilities["web_search"]["last_query"] == "机器人新闻"
    assert session.capabilities["web_search"]["last_summary"] == "两条结果"
    assert [entry["role"] for entry in session.conversation_history] == ["user", "assistant"]


def test_tts_skill_helper_returns_payload_from_latest_user_text_without_committing(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tts", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tts",
        device_id="robot_01",
        text="请播报实验开始。",
        request_id="req_001",
    )

    payload = tts_turn.run_tts_turn(
        text="",
        session_id="sess_tts",
        state_root=state_root,
        env_file=tmp_path / ".ENV",
        artifacts_root=artifacts_root,
    )
    session = sessions.load("sess_tts")

    assert payload["skill_name"] == "tts"
    assert payload["session_result"]["robot_response"]["action"] == "speak"
    assert payload["session_result"]["text"] == "已播报：请播报实验开始。"
    assert session.latest_result is None
    assert session.capabilities == {}


def test_runner_commits_tts_skill_payload_from_bound_session(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tts_commit", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tts_commit",
        device_id="robot_01",
        text="请播报实验开始。",
        request_id="req_001",
    )

    payload = run_ordinary_skill_turn(
        sessions=sessions,
        session_id="sess_tts_commit",
        skill_name="tts",
        env_file=tmp_path / ".ENV",
        build_payload=lambda session, request_id, stale_guard: tts_turn.run_tts_turn(
            text="",
            session_id=session.session_id,
            state_root=state_root,
            env_file=tmp_path / ".ENV",
            artifacts_root=artifacts_root,
            bound_session=session,
            request_id=request_id,
            stale_guard=stale_guard,
        ),
    )
    session = sessions.load("sess_tts_commit")

    assert payload["status"] == "processed"
    assert session.latest_result["text"] == "已播报：请播报实验开始。"
    assert session.capabilities["tts"]["last_text"] == "请播报实验开始。"


def test_runner_drops_stale_tts_turn_before_side_effect(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tts_stale", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tts_stale",
        device_id="robot_01",
        text="请先播报旧请求。",
        request_id="req_old",
    )
    sessions.append_chat_request(
        session_id="sess_tts_stale",
        device_id="robot_01",
        text="这是新的请求。",
        request_id="req_new",
    )

    called = {"value": False}

    def _unexpected_tts(*args, **kwargs):
        called["value"] = True
        raise AssertionError("stale tts turn should not execute side effect")

    monkeypatch.setattr(tts_turn, "_real_tts", _unexpected_tts)

    payload = run_ordinary_skill_turn(
        sessions=sessions,
        session_id="sess_tts_stale",
        skill_name="tts",
        env_file=tmp_path / ".ENV",
        request_id="req_old",
        build_payload=lambda session, request_id, stale_guard: tts_turn.run_tts_turn(
            text="",
            session_id=session.session_id,
            state_root=state_root,
            env_file=tmp_path / ".ENV",
            artifacts_root=artifacts_root,
            bound_session=session,
            request_id=request_id,
            stale_guard=stale_guard,
        ),
    )
    session = sessions.load("sess_tts_stale")

    assert payload["status"] == "dropped"
    assert payload["reason"] == "stale_request"
    assert called["value"] is False
    assert session.latest_result is None
    assert session.capabilities == {}


def test_tracking_skill_trigger_updates_session_with_clarification_when_frames_missing(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")

    payload = process_tracking_init_direct(
        sessions=sessions,
        session_id="sess_tracking",
        device_id="robot_01",
        text="请跟踪穿黑衣服的人",
        request_id="req_tracking_001",
        env_file=tmp_path / ".ENV",
        artifacts_root=artifacts_root,
    )
    session = sessions.load("sess_tracking")

    assert payload["skill_name"] == "tracking"
    assert payload["tool"] == "init"
    assert payload["session_result"]["needs_clarification"] is True
    assert "当前无法确认目标" in payload["session_result"]["text"]
    assert session.latest_result["function"] == "chat"
    assert session.capabilities["tracking"]["pending_question"] == "当前无法确认目标，请补充描述。"


def test_tracking_clarification_reply_routes_back_to_init_path(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking",
        patch={
            "pending_question": "当前无法确认目标，请补充描述。",
            "latest_target_id": None,
            "lifecycle_status": "seeking",
        },
    )

    captured: dict[str, object] = {}

    def _fake_init(**kwargs):
        captured.update(kwargs)
        return {"status": "processed", "skill_name": "tracking", "tool": "init"}

    monkeypatch.setattr(tracking_deterministic, "process_tracking_init_direct", _fake_init)

    payload = tracking_deterministic.process_tracking_request_direct(
        sessions=sessions,
        session_id="sess_tracking",
        device_id="robot_01",
        text="穿黑衣服，白鞋。",
        request_id="req_clarify",
        env_file=tmp_path / ".ENV",
        artifacts_root=artifacts_root,
    )

    assert payload["tool"] == "init"
    assert captured["text"] == "穿黑衣服，白鞋。"
    assert captured["append_chat_request"] is False
    assert len(sessions.load("sess_tracking").conversation_history) == 1


def test_web_search_skill_helper_uses_latest_user_text_without_committing(tmp_path: Path) -> None:
    search_turn = _load_script_module(
        ROOT / "skills" / "web-search" / "scripts" / "search_turn.py",
        "test_web_search_turn",
    )
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_search", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_search",
        device_id="robot_01",
        text="帮我查一下机器人新闻",
        request_id="req_search_001",
    )

    payload = search_turn.run_web_search_turn(
        query="",
        session_id="sess_search",
        state_root=state_root,
        env_file=tmp_path / ".ENV",
        max_results=5,
        include_answer=False,
    )
    session = sessions.load("sess_search")

    assert payload["skill_name"] == "web_search"
    assert payload["tool"] == "search"
    assert payload["tool_output"]["query"] == "帮我查一下机器人新闻"
    assert payload["tool_output"]["error"] == "missing TAVILY_API_KEY"
    assert "当前还不能执行网页搜索" in payload["session_result"]["text"]
    assert session.latest_result is None


def test_feishu_skill_helper_returns_payload_without_committing(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_notify", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_notify",
        device_id="robot_01",
        text="系统事件：charging_completed。请通知飞书",
        request_id="req_notify_001",
    )

    payload = feishu_turn.run_notify_turn(
        session_id="sess_notify",
        state_root=state_root,
        title="充电完成",
        message="机器人底座充电已完成，请安排下一步。",
        event_type="charging_completed",
        recipient=None,
        recipient_type=None,
        env_file=tmp_path / ".ENV",
        artifacts_root=artifacts_root,
    )
    session = sessions.load("sess_notify")

    assert payload["skill_name"] == "feishu"
    assert payload["tool"] == "notify"
    assert payload["tool_output"]["mode"] == "mock"
    assert "已发送飞书提醒（mock）" in payload["session_result"]["text"]
    assert session.latest_result is None
    assert session.capabilities == {}


def test_runner_drops_stale_feishu_turn_before_outbox_write(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_notify_stale", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_notify_stale",
        device_id="robot_01",
        text="旧通知请求",
        request_id="req_old",
    )
    sessions.append_chat_request(
        session_id="sess_notify_stale",
        device_id="robot_01",
        text="新通知请求",
        request_id="req_new",
    )

    called = {"value": False}

    def _unexpected_outbox(*args, **kwargs):
        called["value"] = True
        raise AssertionError("stale feishu turn should not write outbox")

    monkeypatch.setattr(feishu_turn, "_write_outbox_entry", _unexpected_outbox)

    payload = run_ordinary_skill_turn(
        sessions=sessions,
        session_id="sess_notify_stale",
        skill_name="feishu",
        env_file=tmp_path / ".ENV",
        request_id="req_old",
        build_payload=lambda session, request_id, stale_guard: feishu_turn.run_notify_turn(
            session_id=session.session_id,
            state_root=state_root,
            title="充电完成",
            message="机器人底座充电已完成，请安排下一步。",
            event_type="charging_completed",
            recipient=None,
            recipient_type=None,
            env_file=tmp_path / ".ENV",
            artifacts_root=artifacts_root,
            bound_session=session,
            request_id=request_id,
            stale_guard=stale_guard,
        ),
    )
    session = sessions.load("sess_notify_stale")

    assert payload["status"] == "dropped"
    assert payload["reason"] == "stale_request"
    assert called["value"] is False
    assert session.latest_result is None
    assert session.capabilities == {}


def test_stale_ordinary_payload_does_not_mutate_session_state(tmp_path: Path) -> None:
    sessions = AgentSessionStore(tmp_path / "state")
    sessions.start_fresh_session("sess_stale_generic", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_stale_generic",
        device_id="robot_01",
        text="旧请求",
        request_id="req_old",
    )
    sessions.append_chat_request(
        session_id="sess_stale_generic",
        device_id="robot_01",
        text="新请求",
        request_id="req_new",
    )

    payload = run_ordinary_skill_turn(
        sessions=sessions,
        session_id="sess_stale_generic",
        skill_name="web_search",
        env_file=tmp_path / ".ENV",
        request_id="req_old",
        build_payload=lambda _session, request_id, _stale_guard: processed_skill_payload(
            skill_name="web_search",
            session_result={
                "request_id": request_id,
                "function": "chat",
                **reply_session_result("不应提交"),
            },
            tool="search",
            latest_result_patch={"search_query": "旧请求"},
            skill_state_patch={"last_query": "旧请求"},
        ),
    )
    session = sessions.load("sess_stale_generic")

    assert payload["status"] == "dropped"
    assert session.latest_result is None
    assert session.capabilities == {}


def test_runner_drops_tts_turn_that_becomes_stale_inside_helper(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tts_mid_stale", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_tts_mid_stale",
        device_id="robot_01",
        text="旧请求",
        request_id="req_old",
    )

    original_default_text = tts_turn._default_text
    called = {"value": False}

    def _mutating_default_text(session):
        sessions.append_chat_request(
            session_id=session.session_id,
            device_id="robot_01",
            text="新请求",
            request_id="req_new",
        )
        return original_default_text(session)

    def _unexpected_tts(*args, **kwargs):
        called["value"] = True
        raise AssertionError("mid-helper stale tts turn should not execute side effect")

    monkeypatch.setattr(tts_turn, "_default_text", _mutating_default_text)
    monkeypatch.setattr(tts_turn, "_real_tts", _unexpected_tts)

    payload = run_ordinary_skill_turn(
        sessions=sessions,
        session_id="sess_tts_mid_stale",
        skill_name="tts",
        env_file=tmp_path / ".ENV",
        request_id="req_old",
        build_payload=lambda session, request_id, stale_guard: tts_turn.run_tts_turn(
            text="",
            session_id=session.session_id,
            state_root=state_root,
            env_file=tmp_path / ".ENV",
            artifacts_root=artifacts_root,
            bound_session=session,
            request_id=request_id,
            stale_guard=stale_guard,
        ),
    )

    session = sessions.load("sess_tts_mid_stale")
    assert payload["status"] == "dropped"
    assert payload["drop_stage"] == "before_tts_effect"
    assert called["value"] is False
    assert session.latest_result is None
    assert session.capabilities == {}


def test_runner_drops_feishu_turn_that_becomes_stale_inside_helper(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_feishu_mid_stale", device_id="robot_01")
    sessions.append_chat_request(
        session_id="sess_feishu_mid_stale",
        device_id="robot_01",
        text="旧通知请求",
        request_id="req_old",
    )

    original_default_message = feishu_turn._default_message
    called = {"value": False}

    def _mutating_default_message(session):
        sessions.append_chat_request(
            session_id=session.session_id,
            device_id="robot_01",
            text="新通知请求",
            request_id="req_new",
        )
        return original_default_message(session)

    def _unexpected_outbox(*args, **kwargs):
        called["value"] = True
        raise AssertionError("mid-helper stale feishu turn should not write outbox")

    monkeypatch.setattr(feishu_turn, "_default_message", _mutating_default_message)
    monkeypatch.setattr(feishu_turn, "_write_outbox_entry", _unexpected_outbox)

    payload = run_ordinary_skill_turn(
        sessions=sessions,
        session_id="sess_feishu_mid_stale",
        skill_name="feishu",
        env_file=tmp_path / ".ENV",
        request_id="req_old",
        build_payload=lambda session, request_id, stale_guard: feishu_turn.run_notify_turn(
            session_id=session.session_id,
            state_root=state_root,
            title="充电完成",
            message=None,
            event_type="charging_completed",
            recipient=None,
            recipient_type=None,
            env_file=tmp_path / ".ENV",
            artifacts_root=artifacts_root,
            bound_session=session,
            request_id=request_id,
            stale_guard=stale_guard,
        ),
    )

    session = sessions.load("sess_feishu_mid_stale")
    assert payload["status"] == "dropped"
    assert payload["drop_stage"] == "before_feishu_outbox"
    assert called["value"] is False
    assert session.latest_result is None
    assert session.capabilities == {}
