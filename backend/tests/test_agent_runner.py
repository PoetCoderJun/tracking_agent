from __future__ import annotations

from pathlib import Path
import json

import pytest
from PIL import Image

import agent.pi_protocol as pi_protocol_module
import agent.runner as runner_module
from agent import PiAgentRunner
from backend.perception import LocalPerceptionService, RobotDetection, RobotFrame, RobotIngestEvent
import backend.tracking.deterministic as tracking_orchestration_module


@pytest.fixture(autouse=True)
def _stub_route_stage(monkeypatch):
    def _fake_route(**kwargs):
        session = kwargs["session"]
        allowed = list(kwargs.get("allowed_skill_names") or [])
        history = list(session.session.get("conversation_history") or [])
        latest_user_text = ""
        for entry in reversed(history):
            if isinstance(entry, dict) and str(entry.get("role", "")).strip() == "user":
                latest_user_text = str(entry.get("text", "")).strip()
                if latest_user_text:
                    break
        lowered = latest_user_text.lower()
        if "搜索" in lowered or "search" in lowered or "新闻" in lowered:
            return {"decision": "use_skills", "skill_names": ["web_search"], "reply_text": None, "reason": None}
        if "飞书" in lowered or "feishu" in lowered or "通知" in lowered:
            return {"decision": "use_skills", "skill_names": ["feishu"], "reply_text": None, "reason": None}
        if "看到" in lowered or "画面" in lowered or "描述" in lowered:
            return {"decision": "direct_reply", "skill_names": None, "reply_text": "我看到一个人。", "reason": None}
        if "tracking" in allowed:
            return {"decision": "use_skills", "skill_names": ["tracking"], "reply_text": None, "reason": None}
        if allowed:
            return {"decision": "use_skills", "skill_names": [allowed[0]], "reply_text": None, "reason": None}
        return {"decision": "idle", "skill_names": None, "reply_text": None, "reason": "no route"}

    monkeypatch.setattr(runner_module, "_run_pi_route", _fake_route)


def _structured_memory(summary: str) -> dict:
    return {
        "core": summary,
        "front_view": "",
        "back_view": "",
        "distinguish": "",
    }


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def _write_observation(
    runner: PiAgentRunner,
    *,
    session_id: str,
    frame_path: Path,
    text: str = "camera observation",
    request_id: str,
    request_function: str = "observation",
    detections: list[RobotDetection] | None = None,
) -> None:
    LocalPerceptionService(runner.sessions.state_root).write_observation(
        RobotIngestEvent(
            session_id=session_id,
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=list(detections or []),
            text=text,
        ),
        request_id=request_id,
        request_function=request_function,
        record_conversation=(request_function != "observation"),
    )


def test_pi_agent_runner_processes_event_and_updates_memory(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_001",
        frame_path=frame_path,
        request_id="req_obs_001",
        detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
    )

    monkeypatch.setattr(
        "agent.runner._run_pi_turn",
        lambda **_: {
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {
                "behavior": "track",
                "text": "继续跟踪当前目标。",
                "frame_id": "frame_000001",
                "target_id": 12,
                "found": True,
                "robot_response": {
                    "request_id": "req_001",
                    "session_id": "sess_001",
                    "function": "tracking",
                    "frame_id": "frame_000001",
                    "action": "track",
                    "text": "继续跟踪当前目标。",
                    "target_id": 12,
                },
            },
            "latest_result_patch": {"memory": _structured_memory("更新后的 memory")},
            "skill_state_patch": {
                "latest_target_id": 12,
                "latest_memory": _structured_memory("更新后的 memory"),
                "last_tool": "track",
                "pi_orchestrated": True,
            },
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": {
                "request_id": "req_001",
                "session_id": "sess_001",
                "function": "tracking",
                "frame_id": "frame_000001",
                "action": "track",
                "text": "继续跟踪当前目标。",
                "target_id": 12,
            },
            "tool": "track",
            "tool_output": {"behavior": "track", "text": "继续跟踪当前目标。"},
            "rewrite_output": {"task": "update", "memory": _structured_memory("更新后的 memory")},
            "reason": None,
        },
    )

    result = runner.process_chat_request(
        session_id="sess_001",
        device_id="robot_01",
        text="继续跟踪",
        request_id="req_001",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["status"] == "processed"
    assert result["skill_name"] == "tracking"
    assert result["tool"] == "track"
    assert "memory" not in result["latest_result"]
    context = runner.sessions.load("sess_001")
    assert context.skill_cache["tracking"]["last_tool"] == "track"
    assert context.skill_cache["tracking"]["pi_orchestrated"] is True


def test_start_fresh_session_resets_tracking_memory(tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    runner.sessions.patch_skill_state(
        "sess_reset",
        skill_name="tracking",
        patch={"latest_memory": _structured_memory("旧 memory"), "latest_target_id": 9},
    )

    runner.sessions.start_fresh_session("sess_reset", device_id="robot_01")

    context = runner.sessions.load("sess_reset")
    assert context.user_preferences == {}
    assert context.environment_map == {}
    assert context.perception_cache == {}
    assert context.skill_cache == {}


def test_runner_schedules_tracking_memory_rewrite_from_payload(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_async",
        frame_path=frame_path,
        request_id="req_obs_async",
        detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
    )

    scheduled: list[dict[str, object]] = []

    monkeypatch.setattr(
        tracking_orchestration_module,
        "schedule_tracking_memory_rewrite",
        lambda **kwargs: scheduled.append(kwargs),
    )
    monkeypatch.setattr(
        "agent.runner._run_pi_turn",
        lambda **_: {
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {
                "behavior": "track",
                "text": "继续跟踪当前目标。",
                "frame_id": "frame_000001",
                "target_id": 12,
                "found": True,
            },
            "latest_result_patch": None,
            "skill_state_patch": {
                "latest_target_id": 12,
                "latest_confirmed_frame_path": str(frame_path),
            },
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": None,
            "tool": "track",
            "tool_output": {"behavior": "track", "text": "继续跟踪当前目标。"},
            "rewrite_output": None,
            "rewrite_memory_input": {
                "task": "update",
                "crop_path": str(tmp_path / "crop.jpg"),
                "frame_paths": [str(frame_path)],
                "frame_id": "frame_000001",
                "target_id": 12,
                "confirmation_reason": "黑衣服和浅色裤子一致。",
                "candidate_checks": [
                    {"bounding_box_id": 12, "status": "match", "evidence": "核心特征一致"}
                ],
            },
            "reason": None,
        },
    )

    result = runner.process_chat_request(
        session_id="sess_async",
        device_id="robot_01",
        text="继续跟踪",
        request_id="req_async",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["status"] == "processed"
    assert len(scheduled) == 1
    assert scheduled[0]["session_id"] == "sess_async"
    assert scheduled[0]["rewrite_memory_input"]["frame_id"] == "frame_000001"
    assert scheduled[0]["rewrite_memory_input"]["confirmation_reason"] == "黑衣服和浅色裤子一致。"


def test_runner_runs_init_memory_rewrite_synchronously(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_init",
        frame_path=frame_path,
        request_id="req_obs_init",
        detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
    )

    monkeypatch.setattr(
        tracking_orchestration_module,
        "execute_rewrite_memory_tool",
        lambda **_: {
            "task": "init",
            "memory": _structured_memory("黑色上衣、浅色裤子、白鞋。"),
            "frame_id": "frame_000001",
            "target_id": 12,
            "crop_path": str(tmp_path / "crop.jpg"),
            "reference_view": "front",
            "elapsed_seconds": 0.05,
        },
    )
    monkeypatch.setattr(
        "agent.runner._run_pi_turn",
        lambda **_: {
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {
                "behavior": "init",
                "text": "已确认跟踪 ID 为 12 的目标。",
                "frame_id": "frame_000001",
                "target_id": 12,
                "found": True,
            },
            "latest_result_patch": None,
            "skill_state_patch": {
                "latest_target_id": 12,
                "latest_confirmed_frame_path": str(frame_path),
            },
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": None,
            "tool": "init",
            "tool_output": {"behavior": "init", "text": "已确认跟踪 ID 为 12 的目标。"},
            "rewrite_output": None,
            "rewrite_memory_input": {
                "task": "init",
                "crop_path": str(tmp_path / "crop.jpg"),
                "frame_paths": [str(frame_path)],
                "frame_id": "frame_000001",
                "target_id": 12,
            },
            "reason": None,
        },
    )

    result = runner.process_chat_request(
        session_id="sess_init",
        device_id="robot_01",
        text="开始跟踪穿黑衣服的人",
        request_id="req_init",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["rewrite_output"]["task"] == "init"
    assert result["rewrite_memory_input"] is None
    assert "核心特征：黑色上衣、浅色裤子、白鞋。" in result["session_result"]["text"]
    context = runner.sessions.load("sess_init")
    assert context.skill_cache["tracking"]["latest_memory"] == _structured_memory("黑色上衣、浅色裤子、白鞋。")
    assert "核心特征：黑色上衣、浅色裤子、白鞋。" in context.latest_result["text"]


def test_runner_process_chat_request_uses_pi_for_tracking_init(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state", enabled_skills=["tracking"])
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_chat_init",
        frame_path=frame_path,
        request_id="req_obs_chat_init",
        detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
    )

    def _fake_run_pi_turn(**kwargs: object) -> dict:
        assert kwargs["enabled_skill_names"] == ["tracking"]
        return {
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {
                "behavior": "init",
                "text": "已确认目标。",
                "frame_id": "frame_000001",
                "target_id": 12,
                "found": True,
            },
            "latest_result_patch": None,
            "skill_state_patch": {
                "latest_target_id": 12,
                "target_description": "穿黑衣服的人",
                "latest_confirmed_frame_path": str(frame_path),
            },
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": {"action": "track", "text": "已确认目标。", "target_id": 12},
            "tool": "init",
            "tool_output": {
                "behavior": "init",
                "frame_id": "frame_000001",
                "target_id": 12,
                "bounding_box_id": 12,
                "found": True,
                "decision": "track",
                "text": "已确认目标。",
                "reason": "direct init",
                "confirmed_frame_path": str(frame_path),
                "confirmed_bbox": [10, 20, 30, 40],
                "target_description": "穿黑衣服的人",
            },
            "rewrite_output": None,
            "rewrite_memory_input": None,
            "reason": None,
        }

    monkeypatch.setattr("agent.runner._run_pi_turn", _fake_run_pi_turn)

    result = runner.process_chat_request(
        session_id="sess_chat_init",
        device_id="robot_01",
        text="开始跟踪穿黑衣服的人",
        request_id="req_chat_init",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["status"] == "processed"
    assert result["tool"] == "init"
    assert result["session_result"]["target_id"] == 12


def test_runner_dynamically_loads_no_skills_for_plain_scene_question(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state", enabled_skills=["tracking", "web_search", "feishu"])

    def _fake_run_pi_turn(**kwargs: object) -> dict:
        assert kwargs["enabled_skill_names"] == []
        return {
            "status": "processed",
            "skill_name": "agent",
            "session_result": {"behavior": "reply", "text": "我看到一个人。"},
            "latest_result_patch": None,
            "skill_state_patch": None,
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": None,
            "tool": "reply",
            "tool_output": None,
            "rewrite_output": None,
            "rewrite_memory_input": None,
            "reason": None,
        }

    monkeypatch.setattr("agent.runner._run_pi_turn", _fake_run_pi_turn)

    result = runner.process_chat_request(
        session_id="sess_plain_scene",
        device_id="robot_01",
        text="请详细描述现在你看到的画面",
        request_id="req_plain_scene",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["skill_name"] == "agent"
    assert result["tool"] == "reply"


def test_runner_chat_continue_stays_on_pi_path(
    monkeypatch, tmp_path: Path
) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state", enabled_skills=["tracking"])
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_chat_track",
        frame_path=frame_path,
        request_id="req_obs_chat_track",
        detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
    )
    runner.sessions.patch_skill_state(
        "sess_chat_track",
        skill_name="tracking",
        patch={
            "latest_target_id": 12,
            "latest_confirmed_frame_path": str(frame_path),
        },
    )

    monkeypatch.setattr(
        tracking_orchestration_module,
        "process_tracking_request_direct",
        lambda **_: (_ for _ in ()).throw(AssertionError("chat continue should stay on Pi path")),
    )

    def _fake_run_pi_turn(**kwargs: object) -> dict:
        assert kwargs["enabled_skill_names"] == ["tracking"]
        return {
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {
                "behavior": "track",
                "frame_id": "frame_000001",
                "target_id": 12,
                "bounding_box_id": 12,
                "found": False,
                "decision": "wait",
                "text": "当前不确定，保持等待。",
                "reason": "ambiguous",
            },
            "latest_result_patch": None,
            "skill_state_patch": {"pending_question": None},
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": {"action": "wait", "text": "当前不确定，保持等待。"},
            "tool": "track",
            "tool_output": {
                "behavior": "track",
                "decision": "wait",
                "text": "当前不确定，保持等待。",
                "reason": "ambiguous",
            },
            "rewrite_output": None,
            "rewrite_memory_input": None,
            "reason": "ambiguous",
        }

    monkeypatch.setattr(runner_module, "_run_pi_turn", _fake_run_pi_turn)

    result = runner.process_chat_request(
        session_id="sess_chat_track",
        device_id="robot_01",
        text="继续跟踪",
        request_id="req_chat_track",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["status"] == "processed"
    assert result["session_result"]["decision"] == "wait"
    assert result["robot_response"]["action"] == "wait"


def test_runner_grounded_tracking_question_stays_on_pi_path(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state", enabled_skills=["tracking"])
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_tracking_reply",
        frame_path=frame_path,
        request_id="req_obs_tracking_reply",
        detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
    )
    runner.sessions.patch_skill_state(
        "sess_tracking_reply",
        skill_name="tracking",
        patch={
            "latest_target_id": 12,
            "latest_confirmed_frame_path": str(frame_path),
        },
    )

    monkeypatch.setattr(
        tracking_orchestration_module,
        "process_tracking_request_direct",
        lambda **_: (_ for _ in ()).throw(AssertionError("grounded QA should stay on Pi path")),
    )

    def _fake_run_pi_turn(**kwargs: object) -> dict:
        assert kwargs["enabled_skill_names"] == ["tracking"]
        return {
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {
                "behavior": "reply",
                "frame_id": "frame_000001",
                "target_id": 12,
                "bounding_box_id": 12,
                "found": True,
                "text": "目标现在还在右侧。",
                "reason": "grounded reply",
            },
            "latest_result_patch": None,
            "skill_state_patch": None,
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": {"action": "reply", "text": "目标现在还在右侧。"},
            "tool": "reply",
            "tool_output": {"behavior": "reply", "text": "目标现在还在右侧。"},
            "rewrite_output": None,
            "rewrite_memory_input": None,
            "reason": None,
        }

    monkeypatch.setattr(runner_module, "_run_pi_turn", _fake_run_pi_turn)

    result = runner.process_chat_request(
        session_id="sess_tracking_reply",
        device_id="robot_01",
        text="他现在在哪",
        request_id="req_tracking_reply",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["status"] == "processed"
    assert result["tool"] == "reply"
    assert result["session_result"]["text"] == "目标现在还在右侧。"


def test_schedule_tracking_memory_rewrite_spawns_subprocess_worker(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_worker",
        frame_path=frame_path,
        request_id="req_obs_worker",
        detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
    )
    runner.sessions.patch_skill_state(
        "sess_worker",
        skill_name="tracking",
        patch={
            "latest_target_id": 12,
            "latest_confirmed_frame_path": str(frame_path),
        },
    )

    spawned: list[dict[str, object]] = []

    def fake_popen(command, **kwargs):
        spawned.append({"command": command, "kwargs": kwargs})

        class FakeProcess:
            pid = 43210

        return FakeProcess()

    monkeypatch.setattr(tracking_orchestration_module.subprocess, "Popen", fake_popen)

    tracking_orchestration_module.schedule_tracking_memory_rewrite(
        sessions=runner.sessions,
        session_id="sess_worker",
        rewrite_memory_input={
            "task": "update",
            "crop_path": str(tmp_path / "crop.jpg"),
            "frame_paths": [str(frame_path)],
            "frame_id": "frame_000001",
            "target_id": 12,
        },
        env_file=tmp_path / ".ENV",
    )

    assert len(spawned) == 1
    command = spawned[0]["command"]
    assert "-m" in command
    assert "backend.tracking.rewrite_worker" in command
    assert "--session-id" in command
    assert "sess_worker" in command
    assert "--frame-path" in command
    assert str(frame_path) in command
    assert spawned[0]["kwargs"]["start_new_session"] is True


def test_pi_agent_runner_returns_idle_from_pi(tmp_path: Path, monkeypatch) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")

    monkeypatch.setattr(
        "agent.runner._run_pi_turn",
        lambda **_: {
            "status": "idle",
            "skill_name": None,
            "reason": "No installed skill applies.",
        },
    )

    result = runner.process_chat_request(
        session_id="sess_none",
        device_id="robot_01",
        text="hello there",
        request_id="req_none_001",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["status"] == "idle"
    assert result["skill_name"] is None
    assert result["reason"] == "No installed skill applies."


def test_runner_recovers_turn_payload_from_last_assistant_text_part() -> None:
    payload = pi_protocol_module._payload_from_messages(
        [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "ignored prelude",
                    },
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "status": "processed",
                                "skill_name": "tracking",
                                "session_result": {"behavior": "reply", "text": "目标在右侧。"},
                                "latest_result_patch": None,
                                "skill_state_patch": None,
                                "user_preferences_patch": None,
                                "environment_map_patch": None,
                                "perception_cache_patch": None,
                                "robot_response": {"action": "wait"},
                                "tool": "reply",
                                "tool_output": {"behavior": "reply", "text": "目标在右侧。"},
                                "rewrite_output": None,
                                "reason": None,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            }
        ]
    )

    assert payload is not None
    assert payload["status"] == "processed"
    assert payload["skill_name"] == "tracking"
    assert payload["tool"] == "reply"


def test_runner_recovers_turn_payload_from_rpc_agent_end_messages() -> None:
    payload = pi_protocol_module._payload_from_rpc_events(
        [
            {
                "type": "agent_end",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "{\n"
                                    '  "status": "processed",\n'
                                    '  "skill_name": "tracking",\n'
                                    '  "session_result": {"behavior": "reply", "text": "目标在右侧。"},\n'
                                    '  "latest_result_patch": null,\n'
                                    '  "skill_state_patch": null,\n'
                                    '  "user_preferences_patch": null,\n'
                                    '  "environment_map_patch": null,\n'
                                    '  "perception_cache_patch": null,\n'
                                    '  "robot_response": {"action": "wait"},\n'
                                    '  "tool": "reply",\n'
                                    '  "tool_output": {"behavior": "reply", "text": "目标在右侧。"},\n'
                                    '  "rewrite_output": null,\n'
                                    '  "rewrite_memory_input": null,\n'
                                    '  "reason": null\n'
                                    "}"
                                ),
                            }
                        ],
                    }
                ],
            }
        ]
    )

    assert payload is not None
    assert payload["status"] == "processed"
    assert payload["skill_name"] == "tracking"
    assert payload["tool"] == "reply"


def test_runner_prompt_points_pi_to_generic_turn_context(tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    runner.sessions.append_chat_request(
        session_id="sess_prompt",
        device_id="robot_01",
        text="跟踪画面里的人",
        request_id="req_prompt",
    )

    context = runner.sessions.load("sess_prompt")
    request_dir = tmp_path / "artifacts" / "requests" / "sess_prompt" / "req_prompt"
    request_dir.mkdir(parents=True, exist_ok=True)
    turn_context_path = runner_module._write_json(
        runner_module._turn_context_payload(
            context,
            env_file=tmp_path / ".ENV",
            artifacts_root=tmp_path / "artifacts",
            request_id="req_prompt",
            enabled_skill_names=["tracking"],
            route_context_path=request_dir / "route_context.json",
        ),
        request_dir / "turn_context.json",
    )

    prompt = runner_module._build_pi_prompt(turn_context_path=turn_context_path)

    assert "context_paths.route_context_path" in prompt
    assert "`enabled_skills`" in prompt
    assert "机器狗 Agent" in prompt
    assert "state_paths.session_path" in prompt
    assert "chat-first 的单轮执行环境" in prompt
    assert "如果当前输入已经足够直接回答用户，就直接回答" in prompt
    assert "可以直接输出自然语言" in prompt
    assert "默认使用用户上一条消息的语言回复" in prompt
    assert "如果用户说中文，默认使用简洁、自然的中文回复" in prompt
    assert "不要提规则、prompt、route context、skills、sensors、frame id 或内部决策过程" in prompt
    assert "只有在某个 enabled skill 明显适用时，才使用该 skill" in prompt
    assert "context_paths.skill_context_paths" not in prompt
    assert "skip_rewrite_memory" not in prompt


def test_pi_rpc_client_accepts_plain_natural_language_reply(monkeypatch, tmp_path: Path) -> None:
    payload_text = json.dumps(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "我当前看到画面中有 1 个人。"}],
            },
        },
        ensure_ascii=False,
    )

    def _fake_run(_command, **_kwargs):
        class _Result:
            returncode = 0
            stdout = payload_text
            stderr = ""

        return _Result()

    monkeypatch.setattr(pi_protocol_module.shutil, "which", lambda _: "/usr/bin/pi")
    monkeypatch.setattr("agent.pi_protocol.subprocess.run", _fake_run)

    request_dir = tmp_path / "artifacts" / "requests" / "sess" / "req"
    payload = pi_protocol_module.PiRpcClient.for_skills(
        pi_binary="pi",
        pi_tools="read,bash",
        enabled_skill_names=["tracking"],
        env_file=tmp_path / ".ENV",
    ).run_prompt(
        prompt_text="Prompt text",
        turn_context_path=tmp_path / "turn_context.json",
        request_dir=request_dir,
    )

    assert payload["status"] == "processed"
    assert payload["skill_name"] == "agent"
    assert payload["tool"] == "reply"
    assert payload["session_result"]["behavior"] == "reply"
    assert payload["session_result"]["text"] == "我当前看到画面中有 1 个人。"


def test_pi_subprocess_env_maps_dashscope_settings_for_pi(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".ENV"
    env_file.write_text(
        "\n".join(
            [
                "DASHSCOPE_API_KEY=dashscope-key",
                "DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "DASHSCOPE_MODEL=qwen3.5-flash",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FROM_SHELL", "present")

    env = pi_protocol_module._pi_subprocess_env(env_file)

    assert env["FROM_SHELL"] == "present"
    assert env["DASHSCOPE_API_KEY"] == "dashscope-key"
    assert env["OPENAI_API_KEY"] == "dashscope-key"
    assert env["OPENAI_BASE_URL"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_pi_subprocess_env_keeps_explicit_openai_settings(tmp_path: Path) -> None:
    env_file = tmp_path / ".ENV"
    env_file.write_text(
        "\n".join(
            [
                "DASHSCOPE_API_KEY=dashscope-key",
                "DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "OPENAI_API_KEY=openai-key",
                "OPENAI_BASE_URL=https://proxy.example.com/v1",
            ]
        ),
        encoding="utf-8",
    )

    env = pi_protocol_module._pi_subprocess_env(env_file)

    assert env["OPENAI_API_KEY"] == "openai-key"
    assert env["OPENAI_BASE_URL"] == "https://proxy.example.com/v1"


def test_resolve_pi_provider_and_model_prefers_dotenv_dashscope_settings(tmp_path: Path) -> None:
    env_file = tmp_path / ".ENV"
    env_file.write_text(
        "\n".join(
            [
                "DASHSCOPE_API_KEY=dashscope-key",
                "DASHSCOPE_MAIN_MODEL=qwen3.5-flash",
            ]
        ),
        encoding="utf-8",
    )

    provider_model = pi_protocol_module._resolve_pi_provider_and_model(env_file)

    assert provider_model == ("dashscope", "qwen3.5-flash")


def test_resolve_pi_provider_and_model_allows_explicit_pi_override(tmp_path: Path) -> None:
    env_file = tmp_path / ".ENV"
    env_file.write_text(
        "\n".join(
            [
                "DASHSCOPE_API_KEY=dashscope-key",
                "DASHSCOPE_MAIN_MODEL=qwen3.5-flash",
                "PI_PROVIDER=openai",
                "PI_MODEL=gpt-4.1-mini",
            ]
        ),
        encoding="utf-8",
    )

    provider_model = pi_protocol_module._resolve_pi_provider_and_model(env_file)

    assert provider_model == ("openai", "gpt-4.1-mini")


def test_pi_rpc_client_uses_pi_command_with_enabled_skills(tmp_path: Path) -> None:
    env_file = tmp_path / ".ENV"
    env_file.write_text(
        "\n".join(
            [
                "DASHSCOPE_API_KEY=dashscope-key",
                "DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "DASHSCOPE_MAIN_MODEL=qwen3.5-flash",
            ]
        ),
        encoding="utf-8",
    )
    client = pi_protocol_module.PiRpcClient.for_skills(
        pi_binary="pi",
        pi_tools="read,bash",
        enabled_skill_names=["tracking"],
        env_file=env_file,
    )
    command = client.command

    assert command[0] == "pi"
    assert "--mode" in command
    assert "json" in command
    assert "--provider" in command
    assert command[command.index("--provider") + 1] == "dashscope"
    assert "--model" in command
    assert command[command.index("--model") + 1] == "qwen3.5-flash"
    assert "--tools" in command
    tool_arg = command[command.index("--tools") + 1]
    assert "read" in tool_arg
    assert "bash" in tool_arg
    assert "--skill" in command
    assert any(item.endswith("/skills/tracking") for item in command)


def test_pi_rpc_client_runs_pi_and_writes_logs(monkeypatch, tmp_path: Path) -> None:
    payload_text = json.dumps(
        {
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {"behavior": "reply", "text": "ok"},
            "latest_result_patch": None,
            "skill_state_patch": None,
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": None,
            "tool": "reply",
            "tool_output": None,
            "rewrite_output": None,
            "rewrite_memory_input": None,
            "reason": None,
        },
        ensure_ascii=True,
    )
    captured: dict[str, object] = {}

    def _fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs

        class _Result:
            returncode = 0
            stdout = payload_text
            stderr = ""

        return _Result()

    monkeypatch.setattr(pi_protocol_module.shutil, "which", lambda _: "/usr/bin/pi")
    monkeypatch.setattr("agent.pi_protocol.subprocess.run", _fake_run)

    request_dir = tmp_path / "artifacts" / "requests" / "sess" / "req"
    payload = pi_protocol_module.PiRpcClient.for_skills(
        pi_binary="pi",
        pi_tools="read,bash",
        enabled_skill_names=["tracking"],
        env_file=tmp_path / ".ENV",
    ).run_prompt(
        prompt_text="Prompt text",
        turn_context_path=tmp_path / "turn_context.json",
        request_dir=request_dir,
    )

    assert payload["status"] == "processed"
    assert payload["tool"] == "reply"
    if "--prompt-path" in captured["command"] or "--prompt-file" in captured["command"]:
        prompt_flag = "--prompt-path" if "--prompt-path" in captured["command"] else "--prompt-file"
        prompt_path = Path(captured["command"][captured["command"].index(prompt_flag) + 1])
        assert prompt_path.read_text(encoding="utf-8") == "Prompt text"
    else:
        prompt_arg = str(captured["command"][-1])
        assert prompt_arg.startswith("@")
        prompt_path = Path(prompt_arg[1:])
        assert prompt_path.read_text(encoding="utf-8") == "Prompt text"
    assert (request_dir / "pi_stdout.jsonl").read_text(encoding="utf-8") == payload_text


def test_pi_rpc_client_recovers_payload_from_timeout_stdout(monkeypatch, tmp_path: Path) -> None:
    payload_text = json.dumps(
        {
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {"behavior": "init", "text": "ok"},
            "latest_result_patch": None,
            "skill_state_patch": None,
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": None,
            "tool": "init",
            "tool_output": None,
            "rewrite_output": None,
            "rewrite_memory_input": None,
            "reason": None,
        },
        ensure_ascii=True,
    )

    def _fake_run(*_args, **_kwargs):
        raise pi_protocol_module.subprocess.TimeoutExpired(
            cmd=["pi"],
            timeout=90,
            output=(
                '{"type":"message_end","message":{"role":"assistant","content":['
                + json.dumps({"type": "text", "text": payload_text}, ensure_ascii=True)
                + "]}}\n"
            ).encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr(pi_protocol_module.shutil, "which", lambda _: "/usr/bin/pi")
    monkeypatch.setattr("agent.pi_protocol.subprocess.run", _fake_run)

    request_dir = tmp_path / "artifacts" / "requests" / "sess" / "req"
    payload = pi_protocol_module.PiRpcClient.for_skills(
        pi_binary="pi",
        pi_tools="read,bash",
        enabled_skill_names=["tracking"],
        env_file=tmp_path / ".ENV",
    ).run_prompt(
        prompt_text="Prompt text",
        turn_context_path=tmp_path / "turn_context.json",
        request_dir=request_dir,
    )

    assert payload["status"] == "processed"
    assert payload["tool"] == "init"
    assert payload["session_result"]["behavior"] == "init"
    stdout_text = (request_dir / "pi_stdout.jsonl").read_text(encoding="utf-8")
    assert '"type":"message_end"' in stdout_text
    assert '\\"tool\\": \\"init\\"' in stdout_text


def test_pi_rpc_client_attaches_latest_frame_image_from_turn_context(monkeypatch, tmp_path: Path) -> None:
    payload_text = json.dumps(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "我看到一名站着的人。"}],
            },
        },
        ensure_ascii=False,
    )
    frame_path = _frame_image(tmp_path / "frame.jpg")
    route_context_path = tmp_path / "route_context.json"
    route_context_path.write_text(
        json.dumps(
            {
                "latest_frame": {
                    "frame_id": "frame_000001",
                    "timestamp_ms": 1710000000000,
                    "image_path": str(frame_path),
                    "detections": [{"track_id": 12, "bbox": [10, 20, 30, 40], "score": 0.95}],
                }
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    turn_context_path = tmp_path / "turn_context.json"
    turn_context_path.write_text(
        json.dumps(
            {
                "context_paths": {
                    "route_context_path": str(route_context_path),
                }
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def _fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs

        class _Result:
            returncode = 0
            stdout = payload_text
            stderr = ""

        return _Result()

    monkeypatch.setattr(pi_protocol_module.shutil, "which", lambda _: "/usr/bin/pi")
    monkeypatch.setattr("agent.pi_protocol.subprocess.run", _fake_run)

    request_dir = tmp_path / "artifacts" / "requests" / "sess" / "req"
    pi_protocol_module.PiRpcClient.for_skills(
        pi_binary="pi",
        pi_tools="read,bash",
        enabled_skill_names=["tracking"],
        env_file=tmp_path / ".ENV",
    ).run_prompt(
        prompt_text="Prompt text",
        turn_context_path=turn_context_path,
        request_dir=request_dir,
    )

    assert f"@{frame_path}" in captured["command"]


def test_project_skill_paths_include_tracking_skill() -> None:
    skill_paths = runner_module._project_skill_paths()
    names = {path.name for path in skill_paths}
    assert "describe_image" in names
    assert "tracking" in names
    assert "web_search" in names
    assert "feishu" in names


def test_project_skill_paths_can_filter_to_enabled_skills() -> None:
    skill_paths = runner_module._project_skill_paths(["feishu"])

    assert [path.name for path in skill_paths] == ["feishu"]


def test_project_skill_paths_reject_unknown_skill_names() -> None:
    try:
        runner_module._project_skill_paths(["missing-skill"])
    except ValueError as exc:
        assert "Unknown skills requested" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected invalid skill selection to raise ValueError")


def test_runner_uses_session_enabled_skills_when_present(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    runner.sessions.append_chat_request(
        session_id="sess_enabled_skills",
        device_id="robot_01",
        text="请通知飞书",
        request_id="req_enabled_skills",
    )
    runner.sessions.patch_environment(
        "sess_enabled_skills",
        {"agent_runtime": {"enabled_skills": ["feishu"]}},
    )

    def _fake_run_pi_turn(**kwargs: object) -> dict:
        assert kwargs["enabled_skill_names"] == ["feishu"]
        return {
            "status": "idle",
            "skill_name": None,
            "reason": "No installed skill applies.",
        }

    monkeypatch.setattr("agent.runner._run_pi_turn", _fake_run_pi_turn)

    result = runner.process_session(
        session_id="sess_enabled_skills",
        request_id="req_enabled_skills",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["status"] == "idle"


def test_runner_only_loads_web_search_when_turn_explicitly_requests_search(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state", enabled_skills=["tracking", "web_search", "feishu"])

    def _fake_run_pi_turn(**kwargs: object) -> dict:
        assert kwargs["enabled_skill_names"] == ["web_search"]
        return {
            "status": "processed",
            "skill_name": "web_search",
            "session_result": {"behavior": "reply", "text": "这是搜索结果。"},
            "latest_result_patch": None,
            "skill_state_patch": None,
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": None,
            "tool": "search",
            "tool_output": None,
            "rewrite_output": None,
            "rewrite_memory_input": None,
            "reason": None,
        }

    monkeypatch.setattr("agent.runner._run_pi_turn", _fake_run_pi_turn)

    result = runner.process_chat_request(
        session_id="sess_web_only",
        device_id="robot_01",
        text="帮我搜索今天的机器人新闻",
        request_id="req_web_only",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["skill_name"] == "web_search"


def test_runner_flattens_redundant_skill_state_wrapper(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_nested",
        frame_path=frame_path,
        request_id="req_seed",
        text="",
        detections=[RobotDetection(track_id=1, bbox=[10, 20, 30, 40], score=0.95)],
    )

    monkeypatch.setattr(
        "agent.runner._run_pi_turn",
        lambda **_: {
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {
                "behavior": "init",
                "text": "已确认跟踪 ID 为 1 的目标。",
                "frame_id": "frame_000001",
                "target_id": 1,
            },
            "latest_result_patch": None,
            "skill_state_patch": {
                "tracking": {
                    "latest_target_id": 1,
                    "target_description": "ID 为 1 的人",
                }
            },
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": None,
            "tool": "init",
            "tool_output": None,
            "rewrite_output": None,
            "reason": None,
        },
    )

    runner.process_session(
        session_id="sess_nested",
        request_id="req_nested",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    context = runner.sessions.load("sess_nested")
    assert context.skill_cache["tracking"]["latest_target_id"] == 1
    assert "tracking" not in context.skill_cache["tracking"]


def test_runner_does_not_backfill_tracking_fields_from_tool_outputs(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_backfill",
        frame_path=frame_path,
        request_id="req_seed",
        text="",
        detections=[RobotDetection(track_id=1, bbox=[10, 20, 30, 40], score=0.95)],
    )

    monkeypatch.setattr(
        "agent.runner._run_pi_turn",
        lambda **_: {
            "status": "processed",
            "skill_name": "tracking",
            "session_result": {
                "behavior": "reply",
                "text": "还不能确认。",
            },
            "latest_result_patch": None,
            "skill_state_patch": None,
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": None,
            "tool": "init",
            "tool_output": {
                "behavior": "init",
                "frame_id": "frame_000001",
                "target_id": 1,
                "bounding_box_id": 1,
                "found": True,
                "text": "已确认跟踪 ID 为 1 的目标。",
                "latest_target_crop": str(tmp_path / "crop.jpg"),
            },
            "rewrite_output": {
                "task": "init",
                "memory": _structured_memory("更新后的 memory"),
                "crop_path": str(tmp_path / "crop.jpg"),
                "frame_id": "frame_000001",
                "target_id": 1,
            },
            "reason": None,
        },
    )

    result = runner.process_session(
        session_id="sess_backfill",
        request_id="req_backfill",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["session_result"] == {
        "behavior": "reply",
        "text": "还不能确认。",
    }
    context = runner.sessions.load("sess_backfill")
    assert context.skill_cache == {}


def test_runner_processes_web_search_skill_without_backend_special_case(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state", enabled_skills=["web_search"])

    monkeypatch.setattr(
        "agent.runner._run_pi_turn",
        lambda **_: {
            "status": "processed",
            "skill_name": "web_search",
            "session_result": {
                "behavior": "reply",
                "text": "这是搜索结果。",
            },
            "latest_result_patch": {"sources": [{"title": "Example", "url": "https://example.com"}]},
            "skill_state_patch": None,
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": {"action": "reply", "text": "这是搜索结果。"},
            "tool": "search",
            "tool_output": {"query": "机器人新闻"},
            "rewrite_output": None,
            "reason": None,
        },
    )

    result = runner.process_chat_request(
        session_id="sess_web_search",
        device_id="robot_01",
        text="帮我搜索机器人新闻",
        request_id="req_web_search",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["skill_name"] == "web_search"
    assert result["tool"] == "search"
    assert result["latest_result"]["text"] == "这是搜索结果。"


def test_run_pi_turn_uses_latest_persisted_perception_frame_for_route_context(tmp_path: Path, monkeypatch) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state", enabled_skills=["tracking"])
    frame_path = _frame_image(tmp_path / "frame.jpg")
    _write_observation(
        runner,
        session_id="sess_route_frame",
        frame_path=frame_path,
        request_id="req_obs_route_frame",
        detections=[RobotDetection(track_id=3, bbox=[10, 20, 30, 40], score=0.95)],
    )
    session = runner.sessions.append_chat_request(
        session_id="sess_route_frame",
        device_id="robot_01",
        text="请描述当前画面",
        request_id="req_route_frame",
    )

    monkeypatch.setattr(
        runner_module.PiRpcClient,
        "for_skills",
        classmethod(
            lambda cls, **_: type(
                "_Client",
                (),
                {
                    "run_prompt": lambda self, **kwargs: {
                        "status": "idle",
                        "skill_name": None,
                        "reason": "noop",
                    }
                },
            )()
        ),
    )

    runner_module._run_pi_turn(
        pi_binary="pi",
        session=session,
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
        request_id="req_route_frame",
        pi_tools="read,bash",
        enabled_skill_names=["tracking"],
        pi_timeout_seconds=30,
    )

    route_context = json.loads(
        (
            tmp_path
            / "artifacts"
            / "requests"
            / "sess_route_frame"
            / "req_route_frame"
            / "route_context.json"
        ).read_text(encoding="utf-8")
    )
    assert route_context["latest_frame"]["frame_id"] == "frame_000001"
    assert str(route_context["latest_frame"]["image_path"]).endswith("frame_000001.jpg")
    assert "detections" not in route_context["latest_frame"]
    assert "detection_count" not in route_context["latest_frame"]


def test_route_context_omits_assistant_reply_text_to_avoid_style_leakage(tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state", enabled_skills=["tracking"])
    session = runner.sessions.append_chat_request(
        session_id="sess_style",
        device_id="robot_01",
        text="请详细描述你看到的画面",
        request_id="req_style_user",
    )
    session.session["conversation_history"].append(
        {
            "role": "assistant",
            "text": "Based on the current visual input from frame `frame_x`, I can see...",
            "timestamp": "2026-04-07T02:55:19.384572+00:00",
        }
    )
    session.session["latest_result"] = {
        "behavior": "reply",
        "text": "Based on the current visual input from frame `frame_x`, I can see...",
    }

    route_context = runner_module.build_route_context(
        session,
        request_id="req_style_user",
        enabled_skill_names=["tracking"],
        latest_frame=None,
    )

    assert len(route_context["recent_dialogue"]) == 1
    assert route_context["recent_dialogue"][0]["role"] == "user"
    assert route_context["recent_dialogue"][0]["text"] == "请详细描述你看到的画面"
    assert "text" not in route_context["latest_result"]


def test_runner_processes_feishu_skill_without_backend_special_case(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state", enabled_skills=["feishu"])

    monkeypatch.setattr(
        "agent.runner._run_pi_turn",
        lambda **_: {
            "status": "processed",
            "skill_name": "feishu",
            "session_result": {
                "behavior": "reply",
                "text": "已发送飞书提醒（mock）：充电完成",
            },
            "latest_result_patch": {"notification_channel": "feishu"},
            "skill_state_patch": {"last_message_id": "feishu_mock_001"},
            "user_preferences_patch": None,
            "environment_map_patch": None,
            "perception_cache_patch": None,
            "robot_response": {"action": "reply", "text": "已发送飞书提醒（mock）：充电完成"},
            "tool": "notify",
            "tool_output": {"message_id": "feishu_mock_001"},
            "rewrite_output": None,
            "reason": None,
        },
    )

    result = runner.process_chat_request(
        session_id="sess_feishu",
        device_id="robot_01",
        text="系统事件：charging_completed。请通知飞书。",
        request_id="req_feishu",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["skill_name"] == "feishu"
    assert result["tool"] == "notify"
    session = runner.sessions.load("sess_feishu")
    assert session.skills["feishu"]["last_message_id"] == "feishu_mock_001"



def test_runner_does_not_retry_when_pi_returns_no_final_payload(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    attempts = {"count": 0}

    def _fake_run_pi_turn(**_: object) -> dict:
        attempts["count"] += 1
        raise ValueError("Pi did not return a valid turn payload.")

    monkeypatch.setattr("agent.runner._run_pi_turn", _fake_run_pi_turn)

    try:
        runner.process_chat_request(
            session_id="sess_retry",
            device_id="robot_01",
            text="hi",
            request_id="req_retry",
            env_file=tmp_path / ".ENV",
            artifacts_root=tmp_path / "artifacts",
        )
    except ValueError as exc:
        assert "valid turn payload" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected invalid payload to be raised")

    assert attempts["count"] == 1


def test_runner_does_not_retry_after_pi_timeout(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    attempts = {"count": 0}

    def _fake_run_pi_turn(**_: object) -> dict:
        attempts["count"] += 1
        raise RuntimeError("Pi timed out before returning a final payload.")

    monkeypatch.setattr("agent.runner._run_pi_turn", _fake_run_pi_turn)

    try:
        runner.process_chat_request(
            session_id="sess_retry_timeout",
            device_id="robot_01",
            text="hi",
            request_id="req_retry_timeout",
            env_file=tmp_path / ".ENV",
            artifacts_root=tmp_path / "artifacts",
        )
    except RuntimeError as exc:
        assert "timed out" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("Expected timeout to be raised")

    assert attempts["count"] == 1
