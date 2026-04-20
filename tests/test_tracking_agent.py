from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import skills.tracking.scripts.init_turn as tracking_init_turn
from world.perception import LocalPerceptionService, RobotDetection, RobotFrame, RobotIngestEvent
from agent.session import AgentSessionStore
from capabilities.tracking.agent import Re, run_tracking_agent_turn
from capabilities.tracking.deterministic import process_tracking_init_direct
from capabilities.tracking.effects import PENDING_REWRITE_INPUT_KEY
from capabilities.tracking.loop import supervisor_tracking_step
from capabilities.tracking.memory import read_tracking_memory_snapshot, write_tracking_memory_snapshot
from capabilities.tracking.select import _select_with_model, execute_select_tool
from capabilities.tracking.types import TRIGGER_CADENCE_REVIEW, TrackingTrigger
from interfaces.viewer import stream as viewer_stream

ROOT = Path(__file__).resolve().parents[1]


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


def _write_observation(
    *,
    state_root: Path,
    session_id: str,
    image_path: Path,
    frame_id: str = "frame_000001",
    timestamp_ms: int = 1710000000000,
    detections: list[RobotDetection] | None = None,
) -> None:
    perception = LocalPerceptionService(state_root)
    perception.write_observation(
        RobotIngestEvent(
            session_id=session_id,
            device_id="robot_01",
            frame=RobotFrame(
                frame_id=frame_id,
                timestamp_ms=timestamp_ms,
                image_path=str(image_path),
            ),
            detections=list(detections or [RobotDetection(track_id=15, bbox=[10, 12, 36, 44], score=0.95)]),
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
    write_tracking_memory_snapshot(
        state_root=state_root,
        session_id="sess_tracking",
        memory={
            "core": "黑色上衣，浅色裤子。",
            "front_view": "",
            "back_view": "",
            "distinguish": "",
        },
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
    write_tracking_memory_snapshot(
        state_root=state_root,
        session_id="sess_tracking",
        memory={
            "core": "黑色上衣，浅色裤子。",
            "front_view": "",
            "back_view": "",
            "distinguish": "",
        },
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


def test_tracking_init_writes_memory_synchronously_before_tracking_starts(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    artifacts_root = tmp_path / "artifacts"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    image_path = _frame_image(tmp_path / "frame.jpg")
    _write_observation(
        state_root=state_root,
        session_id="sess_tracking",
        image_path=image_path,
        detections=[RobotDetection(track_id=15, bbox=[10, 12, 36, 44], score=0.95)],
    )

    monkeypatch.setattr(
        "capabilities.tracking.deterministic.execute_select_tool",
        lambda **_: {
            "behavior": "init",
            "frame_id": "frame_000001",
            "target_id": 15,
            "bounding_box_id": 15,
            "found": True,
            "decision": "track",
            "text": "已确认目标。",
            "reason": "身份特征一致。",
            "reject_reason": "",
            "needs_clarification": False,
            "clarification_question": None,
            "candidate_checks": [],
            "target_description": "请持续跟踪",
            "rewrite_memory_input": {
                "task": "init",
                "crop_path": str(image_path),
                "frame_paths": [str(image_path)],
                "frame_id": "frame_000001",
                "target_id": 15,
            },
        },
    )
    monkeypatch.setattr(
        "capabilities.tracking.deterministic.execute_rewrite_memory_tool",
        lambda **_: {
            "task": "init",
            "memory": {
                "core": "黑色上衣，黑框眼镜，黑色耳机。",
                "front_view": "正面可见黑框眼镜和黑色头戴式耳机。",
                "back_view": "",
                "distinguish": "近距离半身特写。",
            },
            "crop_path": str(image_path),
            "reference_view": "front",
        },
    )

    payload = process_tracking_init_direct(
        sessions=sessions,
        session_id="sess_tracking",
        device_id="robot_01",
        text="请持续跟踪",
        request_id="req_init",
        env_file=tmp_path / ".ENV",
        artifacts_root=artifacts_root,
    )

    memory_snapshot = read_tracking_memory_snapshot(state_root=state_root, session_id="sess_tracking")
    session = sessions.load("sess_tracking")

    assert payload["status"] == "processed"
    assert session.capabilities["tracking"]["latest_target_id"] == 15
    assert session.capabilities["tracking"].get(PENDING_REWRITE_INPUT_KEY) is None
    assert memory_snapshot["memory"]["core"] == "黑色上衣，黑框眼镜，黑色耳机。"


def test_tracking_result_writes_local_viewer_snapshot(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking",
        patch={"latest_target_id": 15, "lifecycle_status": "bound"},
    )
    write_tracking_memory_snapshot(
        state_root=state_root,
        session_id="sess_tracking",
        memory={
            "core": "黑色上衣，浅色裤子。",
            "front_view": "",
            "back_view": "",
            "distinguish": "",
        },
    )
    image_path = _frame_image(tmp_path / "frame.jpg")
    _write_observation(state_root=state_root, session_id="sess_tracking", image_path=image_path)
    sessions.append_chat_request(
        session_id="sess_tracking",
        device_id="robot_01",
        text="继续跟踪",
        request_id="req_track",
    )
    sessions.apply_skill_result(
        "sess_tracking",
        {
            "request_id": "req_track",
            "function": "chat",
            "behavior": "track",
            "frame_id": "frame_000001",
            "target_id": 15,
            "found": True,
            "decision": "track",
            "text": "继续跟踪当前目标。",
        },
    )

    snapshot_path = state_root / "viewer" / "latest.json"
    frame_path = state_root / "viewer" / "latest.jpg"

    assert snapshot_path.exists()
    assert frame_path.exists()

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert snapshot["session_id"] == "sess_tracking"
    assert snapshot["agent"]["conversation_history"][-1]["text"] == "继续跟踪当前目标。"
    assert snapshot["summary"]["frame_id"] == "frame_000001"
    assert snapshot["modules"]["tracking"]["display_frame"]["rendered_image_path"] == str(frame_path.resolve())
    assert snapshot["modules"]["tracking"]["memory_history"][-1]["memory"]


def test_tracking_init_helper_uses_runtime_env_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_root = tmp_path / "env-state"
    captured: dict[str, object] = {}

    monkeypatch.setenv("ROBOT_AGENT_SESSION_ID", "sess_env")
    monkeypatch.setenv("ROBOT_AGENT_STATE_ROOT", str(state_root))

    def _fake_process_tracking_init_direct(**kwargs):
        captured["session_id"] = kwargs["session_id"]
        captured["state_root"] = kwargs["sessions"].state_root
        captured["text"] = kwargs["text"]
        return {"status": "processed", "session_id": kwargs["session_id"]}

    monkeypatch.setattr(tracking_init_turn, "process_tracking_init_direct", _fake_process_tracking_init_direct)

    exit_code = tracking_init_turn.main(["--text", "请持续跟踪"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert captured["session_id"] == "sess_env"
    assert captured["state_root"] == state_root.resolve()
    assert captured["text"] == "请持续跟踪"
    assert output["status"] == "processed"


def test_tracking_init_helper_prefers_explicit_cli_over_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_state_root = tmp_path / "env-state"
    cli_state_root = tmp_path / "cli-state"
    captured: dict[str, object] = {}

    monkeypatch.setenv("ROBOT_AGENT_SESSION_ID", "sess_env")
    monkeypatch.setenv("ROBOT_AGENT_STATE_ROOT", str(env_state_root))

    def _fake_process_tracking_init_direct(**kwargs):
        captured["session_id"] = kwargs["session_id"]
        captured["state_root"] = kwargs["sessions"].state_root
        return {"status": "processed"}

    monkeypatch.setattr(tracking_init_turn, "process_tracking_init_direct", _fake_process_tracking_init_direct)

    tracking_init_turn.main(
        [
            "--session-id",
            "sess_cli",
            "--state-root",
            str(cli_state_root),
            "--text",
            "请持续跟踪",
        ]
    )

    assert captured["session_id"] == "sess_cli"
    assert captured["state_root"] == cli_state_root.resolve()


def test_tracking_init_helper_requires_explicit_or_runtime_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROBOT_AGENT_SESSION_ID", raising=False)
    monkeypatch.delenv("ROBOT_AGENT_STATE_ROOT", raising=False)

    with pytest.raises(ValueError, match="No active session found"):
        tracking_init_turn.main(
            [
                "--state-root",
                str(tmp_path / "state"),
                "--text",
                "请持续跟踪",
            ]
        )


def test_tracking_skill_contract_spells_out_direct_init_fast_path() -> None:
    skill_text = (ROOT / "skills" / "tracking" / "SKILL.md").read_text(encoding="utf-8")

    assert "call the tracking helper immediately" in skill_text
    assert "Do not preflight by reading `.runtime`, echoing env vars" in skill_text
    assert "Do not turn lifecycle, status, explanation, or already-bound continuation turns into init." in skill_text


def test_viewer_payload_prefers_matching_result_frame(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    sessions = AgentSessionStore(state_root)
    sessions.start_fresh_session("sess_tracking", device_id="robot_01")
    sessions.patch_skill_state(
        "sess_tracking",
        skill_name="tracking",
        patch={"latest_target_id": 15, "lifecycle_status": "bound"},
    )
    first_image = _frame_image(tmp_path / "frame_1.jpg")
    second_image = _frame_image(tmp_path / "frame_2.jpg")
    _write_observation(
        state_root=state_root,
        session_id="sess_tracking",
        image_path=first_image,
        frame_id="frame_000001",
        timestamp_ms=1710000000000,
        detections=[RobotDetection(track_id=15, bbox=[10, 12, 36, 44], score=0.95)],
    )
    _write_observation(
        state_root=state_root,
        session_id="sess_tracking",
        image_path=second_image,
        frame_id="frame_000002",
        timestamp_ms=1710000001000,
        detections=[RobotDetection(track_id=31, bbox=[8, 10, 34, 42], score=0.92)],
    )
    sessions.apply_skill_result(
        "sess_tracking",
        {
            "request_id": "req_track",
            "function": "chat",
            "behavior": "track",
            "frame_id": "frame_000001",
            "target_id": 15,
            "found": True,
            "decision": "track",
            "text": "继续跟踪当前目标。",
        },
    )

    payload = viewer_stream.build_agent_viewer_payload(
        state_root=state_root,
        session_id="sess_tracking",
    )

    assert payload["modules"]["tracking"]["display_frame"]["frame_id"] == "frame_000001"


def test_viewer_cli_defaults_to_local_snapshot_output() -> None:
    args = viewer_stream.parse_args([])

    assert args.state_root == "./.runtime/agent-runtime"
    assert args.output is None


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


def test_supervisor_tracking_step_prioritizes_pending_rewrite_before_new_tracking_turn(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    _write_observation(
        state_root=state_root,
        session_id="sess_tracking",
        image_path=image_path,
        frame_id="frame_000002",
        timestamp_ms=1710000001000,
        detections=[RobotDetection(track_id=15, bbox=[10, 12, 36, 44], score=0.95)],
    )
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
                "core": "黑色上衣，黑框眼镜。",
                "front_view": "",
                "back_view": "",
                "distinguish": "",
            },
            "crop_path": str(image_path),
            "reference_view": "front",
        },
    )
    monkeypatch.setattr(
        "capabilities.tracking.loop.run_tracking_agent_turn",
        lambda **_: (_ for _ in ()).throw(AssertionError("tracking turn should not run before rewrite")),
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
