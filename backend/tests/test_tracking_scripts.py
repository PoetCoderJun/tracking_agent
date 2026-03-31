from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from backend.agent.runtime import LocalAgentRuntime
from backend.config import Settings
from backend.perception import LocalPerceptionService, RobotDetection, RobotFrame, RobotIngestEvent


ROOT = Path(__file__).resolve().parents[2]
TRACKING_SCRIPT_ROOT = ROOT / "skills" / "tracking" / "scripts"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_select():
    return _load_module("tracking_select", TRACKING_SCRIPT_ROOT / "select_target.py")


def _load_rewrite():
    return _load_module("tracking_rewrite", TRACKING_SCRIPT_ROOT / "rewrite_memory.py")


def _load_turn_payload():
    return _load_module("tracking_turn_payload", TRACKING_SCRIPT_ROOT / "turn_payload.py")


def _load_run_init():
    return _load_module("tracking_run_init", TRACKING_SCRIPT_ROOT / "run_tracking_init.py")


def _load_run_track():
    return _load_module("tracking_run_track", TRACKING_SCRIPT_ROOT / "run_tracking_track.py")


def _load_run_worker():
    return _load_module("tracking_run_rewrite_worker", TRACKING_SCRIPT_ROOT / "run_tracking_rewrite_worker.py")


def _load_target_crop():
    return _load_module("tracking_target_crop", ROOT / "skills" / "tracking" / "target_crop.py")


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def _session_payload(frame_path: Path) -> dict:
    return {
        "session_id": "sess_001",
        "device_id": "robot_01",
        "latest_request_id": "req_001",
        "latest_request_function": "chat",
        "conversation_history": [
            {"role": "user", "text": "继续跟踪", "timestamp": "t1"},
        ],
        "recent_frames": [
            {
                "frame_id": "frame_000001",
                "timestamp_ms": 1710000000000,
                "image_path": str(frame_path),
                "detections": [
                    {"track_id": 15, "bbox": [10, 12, 36, 44], "score": 0.95},
                    {"track_id": 16, "bbox": [20, 14, 42, 46], "score": 0.82},
                ],
            }
        ],
    }


def _structured_memory(summary: str) -> dict:
    return {
        "appearance": {
            "head_face": "",
            "upper_body": "",
            "lower_body": "",
            "shoes": "",
            "accessories": "",
            "body_shape": "",
        },
        "distinguish": "",
        "summary": summary,
    }


def _memory_payload(latest_memory: object = "", latest_target_id: int | None = None) -> dict:
    return {
        "user_preferences": {},
        "environment_map": {},
        "perception_cache": {},
        "skill_cache": {
            "tracking": {
                "target_description": "黑衣服的人",
                "latest_memory": latest_memory,
                "latest_target_id": latest_target_id,
                "latest_confirmed_frame_path": "/tmp/reference.jpg" if latest_target_id is not None else None,
            }
        },
    }


def test_tracking_scripts_use_reference_config() -> None:
    select = _load_select()
    rewrite = _load_rewrite()
    assert select.DEFAULT_CONFIG_PATH.exists()
    assert rewrite.DEFAULT_CONFIG_PATH.exists()
    assert select.DEFAULT_CONFIG_PATH.name == "robot-agent-config.json"


def test_select_target_returns_direct_match_for_explicit_init_id(tmp_path: Path) -> None:
    select = _load_select()
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    session_file = tmp_path / "session.json"
    memory_file = tmp_path / "agent_memory.json"
    session_file.write_text(json.dumps(_session_payload(frame_path)), encoding="utf-8")
    memory_file.write_text(json.dumps(_memory_payload()), encoding="utf-8")

    payload = select.execute_select_tool(
        session_file=session_file,
        memory_file=memory_file,
        behavior="init",
        arguments={"target_description": "跟踪 ID 为 15 的人"},
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert payload["behavior"] == "init"
    assert payload["found"] is True
    assert payload["target_id"] == 15
    assert payload["rewrite_memory_input"]["target_id"] == 15


def test_select_target_init_uses_seeded_first_frame_snapshot(tmp_path: Path) -> None:
    select = _load_select()
    first_frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    latest_frame_path = _frame_image(tmp_path / "frames" / "frame_000002.jpg")
    session_file = tmp_path / "session.json"
    memory_file = tmp_path / "agent_memory.json"
    session = _session_payload(latest_frame_path)
    session["recent_frames"] = [
        {
            "frame_id": "frame_000002",
            "timestamp_ms": 1710000001000,
            "image_path": str(latest_frame_path),
            "detections": [
                {"track_id": 16, "bbox": [20, 14, 42, 46], "score": 0.82},
            ],
        }
    ]
    memory = _memory_payload()
    memory["skill_cache"]["tracking"]["init_frame_snapshot"] = {
        "frame_id": "frame_000001",
        "timestamp_ms": 1710000000000,
        "image_path": str(first_frame_path),
        "detections": [
            {"track_id": 15, "bbox": [10, 12, 36, 44], "score": 0.95},
        ],
    }
    session_file.write_text(json.dumps(session), encoding="utf-8")
    memory_file.write_text(json.dumps(memory), encoding="utf-8")

    payload = select.execute_select_tool(
        session_file=session_file,
        memory_file=memory_file,
        behavior="init",
        arguments={"target_description": "跟踪 ID 为 15 的人"},
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert payload["found"] is True
    assert payload["frame_id"] == "frame_000001"
    assert payload["target_id"] == 15


def test_select_target_requests_clarification_for_missing_explicit_id(tmp_path: Path) -> None:
    select = _load_select()
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    session_file = tmp_path / "session.json"
    memory_file = tmp_path / "agent_memory.json"
    session_file.write_text(json.dumps(_session_payload(frame_path)), encoding="utf-8")
    memory_file.write_text(json.dumps(_memory_payload(latest_target_id=15)), encoding="utf-8")

    payload = select.execute_select_tool(
        session_file=session_file,
        memory_file=memory_file,
        behavior="track",
        arguments={"user_text": "改成跟踪 ID 为 99 的人"},
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert payload["behavior"] == "track"
    assert payload["found"] is False
    assert payload["needs_clarification"] is True
    assert "99" in str(payload["clarification_question"])


def test_select_target_track_uses_model_with_memory_guidance(tmp_path: Path, monkeypatch) -> None:
    select = _load_select()
    frame_path = tmp_path / "frames" / "frame_000001.jpg"
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (96, 64), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 36, 56), fill=(20, 20, 20))
    draw.rectangle((48, 8, 78, 56), fill=(220, 40, 40))
    image.save(frame_path, format="JPEG")
    reference_path = _frame_image(tmp_path / "reference.jpg")
    session = _session_payload(frame_path)
    session["recent_frames"][0]["detections"] = [
        {"track_id": 42, "bbox": [8, 8, 36, 56], "score": 0.95},
        {"track_id": 16, "bbox": [48, 8, 78, 56], "score": 0.82},
    ]
    memory = _memory_payload(latest_memory="黑衣服，短发。", latest_target_id=15)
    memory["skill_cache"]["tracking"]["latest_confirmed_frame_path"] = str(reference_path)
    memory["skill_cache"]["tracking"]["latest_confirmed_bbox"] = [8, 8, 36, 56]
    latest_target_crop = tmp_path / "latest_target_crop.jpg"
    Image.new("RGB", (28, 48), color=(20, 20, 20)).save(latest_target_crop, format="JPEG")
    memory["skill_cache"]["tracking"]["latest_target_crop"] = str(latest_target_crop)
    memory["skill_cache"]["tracking"]["identity_target_crop"] = str(latest_target_crop)
    session_file = tmp_path / "session.json"
    memory_file = tmp_path / "agent_memory.json"
    session_file.write_text(json.dumps(session), encoding="utf-8")
    memory_file.write_text(json.dumps(memory), encoding="utf-8")

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
            chat_model="chat",
        )

    calls: list[dict[str, object]] = []

    def fake_call_model(**kwargs):
        calls.append(kwargs)
        return {
            "elapsed_seconds": 0.04,
            "response_text": json.dumps(
                {
                    "found": True,
                    "bounding_box_id": 42,
                    "text": "已确认继续跟踪 ID 42。",
                    "reason": "tracking memory 与 ID 42 的黑衣服和短发特征最一致。",
                    "needs_clarification": False,
                    "clarification_question": None,
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(select, "load_settings", fake_settings)
    monkeypatch.setattr(
        select,
        "call_model",
        fake_call_model,
    )

    payload = select.execute_select_tool(
        session_file=session_file,
        memory_file=memory_file,
        behavior="track",
        arguments={"user_text": "继续跟踪"},
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert payload["found"] is True
    assert payload["target_id"] == 42
    assert payload["rewrite_memory_input"]["task"] == "update"
    assert payload["confirmed_frame_path"].endswith("reference_frames/frame_000001.jpg")
    assert payload["confirmed_bbox"] == [8, 8, 36, 56]
    assert len(calls) == 1
    assert calls[0]["model"] == "main"
    assert len(calls[0]["image_paths"]) == 4
    assert str(reference_path) == str(calls[0]["image_paths"][0])
    assert "tracking memory" in calls[0]["instruction"]
    assert "强特征清单" in calls[0]["instruction"]
    assert "候选 crop 对照" in calls[0]["instruction"]
    assert "黑衣服，短发。" in calls[0]["instruction"]
    assert "frame_000001_candidate_42.jpg" in str(calls[0]["image_paths"][2])
    assert "frame_000001_candidate_16.jpg" in str(calls[0]["image_paths"][3])


def test_select_target_track_survives_source_frame_cleanup(tmp_path: Path, monkeypatch) -> None:
    select = _load_select()
    frame_path = tmp_path / "frames" / "frame_000001.jpg"
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (96, 64), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 36, 56), fill=(20, 20, 20))
    image.save(frame_path, format="JPEG")
    session = _session_payload(frame_path)
    session["recent_frames"][0]["detections"] = [{"track_id": 42, "bbox": [8, 8, 36, 56], "score": 0.95}]
    memory = _memory_payload(latest_memory="黑衣服，短发。", latest_target_id=15)
    reference_path = _frame_image(tmp_path / "reference.jpg")
    memory["skill_cache"]["tracking"]["latest_confirmed_frame_path"] = str(reference_path)
    session_file = tmp_path / "session.json"
    memory_file = tmp_path / "agent_memory.json"
    session_file.write_text(json.dumps(session), encoding="utf-8")
    memory_file.write_text(json.dumps(memory), encoding="utf-8")

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
            chat_model="chat",
        )

    def fake_call_model(**kwargs):
        frame_path.unlink()
        return {
            "elapsed_seconds": 0.04,
            "response_text": json.dumps(
                {
                    "found": True,
                    "bounding_box_id": 42,
                    "text": "已确认继续跟踪 ID 42。",
                    "reason": "tracking memory 与 ID 42 的黑衣服和短发特征最一致。",
                    "needs_clarification": False,
                    "clarification_question": None,
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(select, "load_settings", fake_settings)
    monkeypatch.setattr(select, "call_model", fake_call_model)

    payload = select.execute_select_tool(
        session_file=session_file,
        memory_file=memory_file,
        behavior="track",
        arguments={"user_text": "继续跟踪"},
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert payload["found"] is True
    assert Path(str(payload["latest_target_crop"])).exists()
    assert Path(str(payload["confirmed_frame_path"])).exists()


def test_select_target_recovery_downgrades_ask_to_wait(tmp_path: Path, monkeypatch) -> None:
    select = _load_select()
    frame_path = _frame_image(tmp_path / "frames" / "frame_000050.jpg")
    reference_path = _frame_image(tmp_path / "reference.jpg")
    tracking_context = {
        "session_id": "sess_001",
        "target_description": "黑衣服的人",
        "memory": {
            "appearance": {
                "head_face": "短发，戴眼镜",
                "upper_body": "黑色短袖T恤",
                "lower_body": "卡其色短裤",
                "shoes": "白鞋白袜",
                "accessories": "",
                "body_shape": "",
            },
            "distinguish": "黑T配卡其短裤",
            "summary": "黑T卡其短裤",
        },
        "latest_target_id": 54,
        "latest_confirmed_frame_path": str(reference_path),
        "latest_confirmed_bbox": [10, 12, 36, 44],
        "chat_history": [{"role": "user", "text": "继续跟踪", "timestamp": "t1"}],
        "recovery_mode": True,
        "missing_target_id": 54,
        "candidate_track_id_floor_exclusive": 54,
        "frames": [
            {
                "frame_id": "frame_000050",
                "timestamp_ms": 1710000000000,
                "image_path": str(frame_path),
                "detections": [
                    {"track_id": 63, "bbox": [10, 12, 36, 44], "score": 0.95},
                ],
            }
        ],
    }
    tracking_context_file = tmp_path / "tracking_context.json"
    tracking_context_file.write_text(json.dumps(tracking_context), encoding="utf-8")

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
            chat_model="chat",
        )

    def fake_call_model(**kwargs):
        return {
            "elapsed_seconds": 0.04,
            "response_text": json.dumps(
                {
                    "found": False,
                    "bounding_box_id": None,
                    "text": "请确认是不是 ID63。",
                    "reason": "当前只有一个候选，但下装看不清。",
                    "needs_clarification": True,
                    "clarification_question": "是不是 ID63？",
                    "candidate_checks": [
                        {
                            "bounding_box_id": 63,
                            "status": "unknown",
                            "evidence": "下装和鞋袜看不清",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(select, "load_settings", fake_settings)
    monkeypatch.setattr(select, "call_model", fake_call_model)

    payload = select.execute_select_tool(
        tracking_context_file=tracking_context_file,
        behavior="track",
        arguments={"user_text": "继续跟踪"},
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert payload["found"] is False
    assert payload["decision"] == "wait"
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None
    assert payload["candidate_checks"][0]["bounding_box_id"] == 63


def test_save_target_crop_adds_conservative_padding(tmp_path: Path) -> None:
    target_crop = _load_target_crop()
    image_path = tmp_path / "frame.jpg"
    Image.new("RGB", (120, 160), color="white").save(image_path, format="JPEG")
    output_path = tmp_path / "crop.jpg"

    target_crop.save_target_crop(image_path, [30, 20, 70, 120], output_path)

    with Image.open(output_path) as image:
        width, height = image.size

    assert width > 40
    assert height > 100


def test_rewrite_memory_uses_sub_model_and_normalizes_memory(tmp_path: Path, monkeypatch) -> None:
    rewrite = _load_rewrite()
    crop_path = _frame_image(tmp_path / "crops" / "target.jpg")
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    memory_file = tmp_path / "agent_memory.json"
    memory_file.write_text(
        json.dumps(_memory_payload(latest_memory=_structured_memory("旧记忆。"))),
        encoding="utf-8",
    )

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
            chat_model="chat",
        )

    calls: list[dict[str, object]] = []

    def fake_call_model(**kwargs):
        calls.append(kwargs)
        return {
            "elapsed_seconds": 0.04,
            "response_text": json.dumps(
                {
                    "appearance": {
                        "head_face": "",
                        "upper_body": "黑色上衣。",
                        "lower_body": "浅色裤子。",
                        "shoes": "",
                        "accessories": "",
                        "body_shape": "",
                    },
                    "distinguish": "优先看黑色上衣和浅色裤子。",
                    "summary": "黑色上衣、浅色裤子。",
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(rewrite, "load_settings", fake_settings)
    monkeypatch.setattr(rewrite, "call_model", fake_call_model)

    payload = rewrite.execute_rewrite_memory_tool(
        memory_file=memory_file,
        arguments={
            "task": "update",
            "crop_path": str(crop_path),
            "frame_paths": [str(frame_path)],
            "frame_id": "frame_000001",
            "target_id": 15,
        },
        env_file=tmp_path / ".ENV",
    )

    assert payload["task"] == "update"
    assert payload["target_id"] == 15
    assert payload["memory"]["appearance"]["upper_body"] == "黑色上衣。"
    assert payload["memory"]["appearance"]["lower_body"] == "浅色裤子。"
    assert payload["memory"]["summary"] == "黑色上衣、浅色裤子。"
    assert len(calls) == 1
    assert calls[0]["model"] == "sub"
    assert "当前最近邻相似人" in calls[0]["instruction"]
    assert "相似人A" in calls[0]["instruction"]
    assert ("summary：只写目标自己" in calls[0]["instruction"] or "只写目标自己" in calls[0]["instruction"])
    assert "不要写相似人" in calls[0]["instruction"]
    assert "空字符串" in calls[0]["instruction"]
    assert "位置词" in calls[0]["instruction"]
    assert ("前景/背景" in calls[0]["instruction"] or "远近" in calls[0]["instruction"])
    assert ("不沿用旧场景" in calls[0]["instruction"] or "位置和动作会变" in calls[0]["instruction"])
    assert "身份特征" in calls[0]["instruction"]
    assert "沿用旧值" in calls[0]["instruction"]


def test_turn_payload_builds_processed_tracking_payload(tmp_path: Path) -> None:
    payload_module = _load_turn_payload()
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    crop_path = _frame_image(tmp_path / "crops" / "target.jpg")

    payload = payload_module.build_tracking_turn_payload(
        {
            "behavior": "track",
            "frame_id": "frame_000001",
            "target_id": 15,
            "bounding_box_id": 15,
            "found": True,
            "decision": "track",
            "text": "已确认继续跟踪 ID 为 15 的目标。",
            "reason": "外观一致",
            "latest_target_crop": str(crop_path),
            "target_description": "黑衣服的人",
            "rewrite_memory_input": {
                "task": "update",
                "crop_path": str(crop_path),
                "frame_paths": [str(frame_path)],
                "frame_id": "frame_000001",
                "target_id": 15,
            },
        }
    )

    assert payload["status"] == "processed"
    assert payload["skill_name"] == "tracking"
    assert payload["tool"] == "track"
    assert payload["session_result"]["target_id"] == 15
    assert payload["session_result"]["decision"] == "track"
    assert payload["robot_response"]["action"] == "track"
    assert payload["skill_state_patch"]["latest_confirmed_frame_path"] == str(frame_path)
    assert payload["rewrite_memory_input"]["frame_paths"] == [str(frame_path)]


def test_turn_payload_builds_wait_response_without_pending_question() -> None:
    payload_module = _load_turn_payload()

    payload = payload_module.build_tracking_turn_payload(
        {
            "behavior": "track",
            "frame_id": "frame_000010",
            "target_id": 15,
            "bounding_box_id": 15,
            "found": False,
            "decision": "wait",
            "text": "当前不确定，保持等待。",
            "reason": "最佳候选分数过低（score=0.611）。",
            "target_description": "黑衣服的人",
        }
    )

    assert payload["session_result"]["decision"] == "wait"
    assert payload["skill_state_patch"]["pending_question"] is None
    assert payload["robot_response"]["action"] == "wait"


def test_run_tracking_track_script_returns_final_payload(tmp_path: Path, monkeypatch) -> None:
    run_track = _load_run_track()

    monkeypatch.setattr(
        run_track,
        "execute_select_tool",
        lambda **_: {
            "behavior": "track",
            "frame_id": "frame_000001",
            "target_id": 15,
            "bounding_box_id": 15,
            "found": True,
            "decision": "track",
            "text": "已确认继续跟踪 ID 为 15 的目标。",
            "reason": "外观一致",
            "latest_target_crop": str(tmp_path / "crop.jpg"),
            "target_description": "黑衣服的人",
            "rewrite_memory_input": {
                "task": "update",
                "crop_path": str(tmp_path / "crop.jpg"),
                "frame_paths": [str(tmp_path / "frame.jpg")],
                "frame_id": "frame_000001",
                "target_id": 15,
            },
        },
    )
    monkeypatch.setattr(
        run_track,
        "ensure_rewrite_paths_exist",
        lambda payload: payload,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_tracking_track.py",
            "--session-file",
            str(tmp_path / "session.json"),
            "--memory-file",
            str(tmp_path / "agent_memory.json"),
            "--user-text",
            "继续跟踪",
        ],
    )

    captured: list[str] = []
    monkeypatch.setattr("builtins.print", lambda value: captured.append(value))

    exit_code = run_track.main()

    assert exit_code == 0
    payload = json.loads(captured[0])
    assert payload["status"] == "processed"
    assert payload["tool"] == "track"
    assert payload["session_result"]["frame_id"] == "frame_000001"
    assert payload["robot_response"]["action"] == "track"


def test_rewrite_worker_writes_status_and_result_files(tmp_path: Path, monkeypatch) -> None:
    worker = _load_run_worker()
    state_root = tmp_path / "state"
    runtime = LocalAgentRuntime(state_root=state_root)
    perception = LocalPerceptionService(state_root=state_root)
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    crop_path = _frame_image(tmp_path / "crops" / "target.jpg")
    runtime.start_fresh_session("sess_worker", device_id="robot_01")
    perception.write_observation(
        RobotIngestEvent(
            session_id="sess_worker",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[RobotDetection(track_id=15, bbox=[10, 12, 36, 44], score=0.95)],
            text="camera observation",
        ),
        request_id="req_obs",
        request_function="observation",
    )
    runtime.apply_skill_result(
        "sess_worker",
        {"behavior": "track", "frame_id": "frame_000001", "target_id": 15, "found": True, "text": "继续跟踪"},
    )
    runtime.update_skill_cache(
        "sess_worker",
        skill_name="tracking",
        payload={
            "latest_target_id": 15,
            "latest_confirmed_frame_path": str(frame_path),
            "latest_rewrite_job_id": "rewrite_test_latest",
        },
    )
    memory_file = Path(runtime.context("sess_worker").state_paths["agent_memory_path"])
    job_dir = tmp_path / "job"

    monkeypatch.setattr(
        worker,
        "execute_rewrite_memory_tool",
        lambda **_: {
            "task": "update",
            "memory": _structured_memory("新的 memory"),
            "frame_id": "frame_000001",
            "target_id": 15,
            "crop_path": str(crop_path),
            "elapsed_seconds": 0.05,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_tracking_rewrite_worker.py",
            "--state-root",
            str(state_root),
            "--job-id",
            "rewrite_test_latest",
            "--job-dir",
            str(job_dir),
            "--session-id",
            "sess_worker",
            "--memory-file",
            str(memory_file),
            "--task",
            "update",
            "--crop-path",
            str(crop_path),
            "--frame-path",
            str(frame_path),
            "--frame-id",
            "frame_000001",
            "--target-id",
            "15",
        ],
    )

    exit_code = worker.main()

    assert exit_code == 0
    context = runtime.context("sess_worker")
    assert context.skill_cache["tracking"]["latest_memory"] == _structured_memory("新的 memory")
    status_payload = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    assert status_payload["status"] == "succeeded"
    assert status_payload["exit_code"] == 0
    result_payload = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    assert result_payload["memory"] == _structured_memory("新的 memory")


def test_rewrite_worker_skips_superseded_job(tmp_path: Path, monkeypatch) -> None:
    worker = _load_run_worker()
    state_root = tmp_path / "state"
    runtime = LocalAgentRuntime(state_root=state_root)
    perception = LocalPerceptionService(state_root=state_root)
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    crop_path = _frame_image(tmp_path / "crops" / "target.jpg")
    runtime.start_fresh_session("sess_worker_skip", device_id="robot_01")
    perception.write_observation(
        RobotIngestEvent(
            session_id="sess_worker_skip",
            device_id="robot_01",
            frame=RobotFrame(
                frame_id="frame_000001",
                timestamp_ms=1710000000000,
                image_path=str(frame_path),
            ),
            detections=[RobotDetection(track_id=15, bbox=[10, 12, 36, 44], score=0.95)],
            text="camera observation",
        ),
        request_id="req_obs",
        request_function="observation",
    )
    runtime.apply_skill_result(
        "sess_worker_skip",
        {"behavior": "track", "frame_id": "frame_000001", "target_id": 15, "found": True, "text": "继续跟踪"},
    )
    runtime.update_skill_cache(
        "sess_worker_skip",
        skill_name="tracking",
        payload={
            "latest_target_id": 15,
            "latest_confirmed_frame_path": str(frame_path),
            "latest_memory": _structured_memory("旧 memory"),
            "latest_rewrite_job_id": "rewrite_newer_job",
        },
    )
    memory_file = Path(runtime.context("sess_worker_skip").state_paths["agent_memory_path"])
    job_dir = tmp_path / "job_skip"

    monkeypatch.setattr(
        worker,
        "execute_rewrite_memory_tool",
        lambda **_: (_ for _ in ()).throw(AssertionError("superseded job should not execute rewrite")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_tracking_rewrite_worker.py",
            "--state-root",
            str(state_root),
            "--job-id",
            "rewrite_old_job",
            "--job-dir",
            str(job_dir),
            "--session-id",
            "sess_worker_skip",
            "--memory-file",
            str(memory_file),
            "--task",
            "update",
            "--crop-path",
            str(crop_path),
            "--frame-path",
            str(frame_path),
            "--frame-id",
            "frame_000001",
            "--target-id",
            "15",
        ],
    )

    exit_code = worker.main()

    assert exit_code == 0
    context = runtime.context("sess_worker_skip")
    assert context.skill_cache["tracking"]["latest_memory"] == _structured_memory("旧 memory")
    status_payload = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    assert status_payload["status"] == "skipped"
    assert status_payload["reason"] == "superseded"
