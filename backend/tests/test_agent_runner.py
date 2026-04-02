from __future__ import annotations

from pathlib import Path
import json

from PIL import Image

import backend.agent.runner as runner_module
import skills.tracking.runtime as tracking_orchestration_module
from backend.agent import PiAgentRunner
from backend.perception import LocalPerceptionService, RobotDetection, RobotFrame, RobotIngestEvent


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
        "backend.agent.runner._run_pi_turn",
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
        "backend.agent.runner._run_pi_turn",
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


def test_runner_schedules_init_memory_rewrite_asynchronously(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_init",
        frame_path=frame_path,
        request_id="req_obs_init",
        detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
    )

    scheduled: list[dict[str, object]] = []
    monkeypatch.setattr(
        tracking_orchestration_module,
        "schedule_tracking_memory_rewrite",
        lambda **kwargs: scheduled.append(kwargs),
    )
    monkeypatch.setattr(
        "backend.agent.runner._run_pi_turn",
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

    assert len(scheduled) == 1
    assert scheduled[0]["rewrite_memory_input"]["task"] == "init"
    assert result["rewrite_output"] is None
    assert "memory" not in result["latest_result"]
    context = runner.sessions.load("sess_init")
    assert "latest_memory" not in context.skill_cache["tracking"]


def test_runner_processes_direct_tracking_request(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_direct",
        frame_path=frame_path,
        request_id="req_obs_direct",
        detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
    )

    monkeypatch.setattr(
        tracking_orchestration_module,
        "execute_select_tool",
        lambda **_: {
            "behavior": "track",
            "frame_id": "frame_000001",
            "target_id": 12,
            "bounding_box_id": 12,
            "found": True,
            "decision": "track",
            "text": "已确认继续跟踪 ID 12。",
            "reason": "deterministic rebind",
            "confirmed_frame_path": str(frame_path),
            "confirmed_bbox": [10, 20, 30, 40],
        },
    )

    result = runner.process_tracking_request_direct(
        session_id="sess_direct",
        device_id="robot_01",
        text="继续跟踪",
        request_id="req_direct",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["status"] == "processed"
    assert result["tool"] == "track"
    assert result["session_result"]["target_id"] == 12
    assert result["robot_response"]["action"] == "track"
    context = runner.sessions.load("sess_direct")
    assert context.skill_cache["tracking"]["latest_target_id"] == 12


def test_runner_process_chat_request_bypasses_pi_for_tracking_init(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state", enabled_skills=["tracking"])
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_chat_init",
        frame_path=frame_path,
        request_id="req_obs_chat_init",
        detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
    )

    monkeypatch.setattr(
        tracking_orchestration_module,
        "execute_select_tool",
        lambda **_: {
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
        },
    )
    monkeypatch.setattr(
        PiAgentRunner,
        "process_session",
        lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("Pi should not be used for tracking init")),
    )

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


def test_runner_direct_tracking_returns_wait_without_pi_fallback_on_uncertainty(
    monkeypatch, tmp_path: Path
) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    _write_observation(
        runner,
        session_id="sess_direct_fallback",
        frame_path=frame_path,
        request_id="req_obs_direct_fallback",
        detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
    )

    monkeypatch.setattr(
        tracking_orchestration_module,
        "execute_select_tool",
        lambda **_: {
            "behavior": "track",
            "frame_id": "frame_000001",
            "target_id": 12,
            "bounding_box_id": 12,
            "found": False,
            "decision": "wait",
            "text": "当前不确定，保持等待。",
            "reason": "ambiguous",
        },
    )
    monkeypatch.setattr(
        PiAgentRunner,
        "process_session",
        lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("Pi fallback should not be used")),
    )

    result = runner.process_tracking_request_direct(
        session_id="sess_direct_fallback",
        device_id="robot_01",
        text="继续跟踪",
        request_id="req_direct_fallback",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["status"] == "processed"
    assert result["session_result"]["decision"] == "wait"
    assert result["robot_response"]["action"] == "wait"


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
    assert "skills/tracking/scripts/rewrite_worker.py" in command
    assert "--session-id" in command
    assert "sess_worker" in command
    assert "--frame-path" in command
    assert str(frame_path) in command
    assert spawned[0]["kwargs"]["start_new_session"] is True


def test_pi_agent_runner_returns_idle_from_pi(tmp_path: Path, monkeypatch) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")

    monkeypatch.setattr(
        "backend.agent.runner._run_pi_turn",
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


def test_runner_recovers_turn_payload_from_later_assistant_text_part() -> None:
    payload = runner_module._payload_from_messages(
        [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "I inspected the state files and now return the final payload.",
                    },
                    {
                        "type": "text",
                        "text": (
                            "```json\n"
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
                            '  "reason": null\n'
                            "}\n"
                            "```"
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


def test_runner_prompt_points_pi_to_context_views(tmp_path: Path) -> None:
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
            tracking_context_path=request_dir / "tracking_context.json",
        ),
        request_dir / "turn_context.json",
    )

    prompt = runner_module._build_pi_prompt(turn_context_path=turn_context_path)

    assert "context_paths.route_context_path" in prompt
    assert "context_paths.tracking_context_path" in prompt
    assert "`enabled_skills`" in prompt
    assert "Available project skills are already loaded natively into Pi" in prompt
    assert "Only read `state_paths.session_path`" in prompt
    assert "Never write the final payload into a temp file such as `pi_output.json`" in prompt
    assert "`idle` is only for turns where no installed skill applies" in prompt
    assert "copy those canonical fields directly into `session_result`" in prompt
    assert "skip_rewrite_memory" not in prompt


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

    env = runner_module._pi_subprocess_env(env_file)

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

    env = runner_module._pi_subprocess_env(env_file)

    assert env["OPENAI_API_KEY"] == "openai-key"
    assert env["OPENAI_BASE_URL"] == "https://proxy.example.com/v1"


def test_pi_command_uses_dashscope_model_with_openai_provider(tmp_path: Path) -> None:
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
    prompt_path = tmp_path / "pi_prompt.md"
    prompt_path.write_text("prompt", encoding="utf-8")

    command = runner_module._pi_command(
        pi_binary="pi",
        pi_tools="read,bash",
        enabled_skill_names=["tracking"],
        prompt_path=prompt_path,
        env_file=env_file,
    )

    assert "--provider" in command
    assert "dashscope" in command
    assert "--model" in command
    assert "qwen3.5-flash" in command
    assert "--skill" in command
    assert command[-1] == f"@{prompt_path}"


def test_project_skill_paths_include_tracking_skill() -> None:
    skill_paths = runner_module._project_skill_paths()
    names = {path.name for path in skill_paths}
    assert "tracking" in names


def test_project_skill_paths_can_filter_to_enabled_skills() -> None:
    skill_paths = runner_module._project_skill_paths(["speech"])

    assert [path.name for path in skill_paths] == ["speech"]


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
        text="hello",
        request_id="req_enabled_skills",
    )
    runner.sessions.patch_environment(
        "sess_enabled_skills",
        {"agent_runtime": {"enabled_skills": ["speech"]}},
    )

    def _fake_run_pi_turn(**kwargs: object) -> dict:
        assert kwargs["enabled_skill_names"] == ["speech"]
        return {
            "status": "idle",
            "skill_name": None,
            "reason": "No installed skill applies.",
        }

    monkeypatch.setattr("backend.agent.runner._run_pi_turn", _fake_run_pi_turn)

    result = runner.process_session(
        session_id="sess_enabled_skills",
        request_id="req_enabled_skills",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert result["status"] == "idle"


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
        "backend.agent.runner._run_pi_turn",
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
        "backend.agent.runner._run_pi_turn",
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


def test_runner_retries_once_when_pi_returns_no_final_payload(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    attempts = {"count": 0}

    def _fake_run_pi_turn(**_: object) -> dict:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ValueError("Pi did not return a valid turn payload.")
        return {
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
            "reason": None,
        }

    monkeypatch.setattr("backend.agent.runner._run_pi_turn", _fake_run_pi_turn)

    result = runner.process_chat_request(
        session_id="sess_retry",
        device_id="robot_01",
        text="hi",
        request_id="req_retry",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert attempts["count"] == 2
    assert result["status"] == "processed"


def test_runner_retries_after_pi_timeout(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    attempts = {"count": 0}

    def _fake_run_pi_turn(**_: object) -> dict:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("Pi timed out before returning a final payload.")
        return {
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
            "reason": None,
        }

    monkeypatch.setattr("backend.agent.runner._run_pi_turn", _fake_run_pi_turn)

    result = runner.process_chat_request(
        session_id="sess_retry_timeout",
        device_id="robot_01",
        text="hi",
        request_id="req_retry_timeout",
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert attempts["count"] == 2
    assert result["status"] == "processed"
