from __future__ import annotations

from pathlib import Path

from PIL import Image

import backend.agent.runner as runner_module
from backend.agent import PiAgentRunner
from backend.perception import RobotDetection, RobotFrame, RobotIngestEvent


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def test_pi_agent_runner_processes_event_and_updates_memory(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    runner.runtime.ingest_event(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
            text="camera observation",
        ),
        request_id="req_obs_001",
        request_function="observation",
        record_conversation=False,
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
            "latest_result_patch": {"memory": "更新后的 memory"},
            "skill_state_patch": {
                "latest_target_id": 12,
                "latest_memory": "更新后的 memory",
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
            "rewrite_output": {"task": "update", "memory": "更新后的 memory"},
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
    assert result["latest_result"]["memory"] == "更新后的 memory"
    context = runner.runtime.context("sess_001")
    assert context.skill_cache["tracking"]["last_tool"] == "track"
    assert context.skill_cache["tracking"]["pi_orchestrated"] is True


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


def test_runner_prompt_points_pi_to_state_files(tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    runner.runtime.append_chat_request(
        session_id="sess_prompt",
        device_id="robot_01",
        text="跟踪画面里的人",
        request_id="req_prompt",
    )

    context = runner.runtime.context("sess_prompt")
    request_dir = tmp_path / "artifacts" / "requests" / "sess_prompt" / "req_prompt"
    request_dir.mkdir(parents=True, exist_ok=True)
    turn_context_path = runner_module._write_json(
        runner_module._turn_context_payload(
            context,
            env_file=tmp_path / ".ENV",
            artifacts_root=tmp_path / "artifacts",
            request_id="req_prompt",
            enabled_skill_names=["tracking"],
        ),
        request_dir / "turn_context.json",
    )

    prompt = runner_module._build_pi_prompt(turn_context_path=turn_context_path)

    assert "state_paths.session_path" in prompt
    assert "state_paths.agent_memory_path" in prompt
    assert "`enabled_skills`" in prompt
    assert "Available project skills are already loaded natively into Pi" in prompt
    assert "Never edit `state_paths.session_path`, `state_paths.agent_memory_path`" in prompt
    assert "Never write the final payload into a temp file such as `pi_output.json`" in prompt
    assert "`idle` is only for turns where no installed skill applies" in prompt
    assert "copy those canonical fields directly into `session_result`" in prompt
    assert "skip_rewrite_memory" not in prompt


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
    runner.runtime.append_chat_request(
        session_id="sess_enabled_skills",
        device_id="robot_01",
        text="hello",
        request_id="req_enabled_skills",
    )
    runner.runtime.update_environment_map(
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

    runner.runtime.ingest_event(
        RobotIngestEvent(
            session_id="sess_nested",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[RobotDetection(track_id=1, bbox=[10, 20, 30, 40], score=0.95)],
            text="",
        ),
        request_id="req_seed",
        request_function="observation",
        record_conversation=False,
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

    context = runner.runtime.context("sess_nested")
    assert context.skill_cache["tracking"]["latest_target_id"] == 1
    assert "tracking" not in context.skill_cache["tracking"]


def test_runner_does_not_backfill_tracking_fields_from_tool_outputs(monkeypatch, tmp_path: Path) -> None:
    runner = PiAgentRunner(state_root=tmp_path / "state")
    frame_path = _frame_image(tmp_path / "frame.jpg")

    runner.runtime.ingest_event(
        RobotIngestEvent(
            session_id="sess_backfill",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[RobotDetection(track_id=1, bbox=[10, 20, 30, 40], score=0.95)],
            text="",
        ),
        request_id="req_seed",
        request_function="observation",
        record_conversation=False,
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
                "memory": "更新后的 memory",
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
    context = runner.runtime.context("sess_backfill")
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
