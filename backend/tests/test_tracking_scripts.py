from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from backend.runtime_session import AgentSessionStore
from backend.config import Settings
from backend.perception import LocalPerceptionService, RobotDetection, RobotFrame, RobotIngestEvent
from backend.tracking.deterministic import schedule_tracking_memory_rewrite


ROOT = Path(__file__).resolve().parents[2]
TRACKING_BACKEND_ROOT = ROOT / "backend" / "tracking"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_select():
    return _load_module("tracking_select", TRACKING_BACKEND_ROOT / "select.py")


def _load_rewrite():
    return _load_module("tracking_rewrite", TRACKING_BACKEND_ROOT / "rewrite_memory.py")


def _load_turn_payload():
    return _load_module("tracking_turn_payload", TRACKING_BACKEND_ROOT / "payload.py")


def _load_run_init():
    return _load_module("tracking_run_init", TRACKING_BACKEND_ROOT / "cli.py")


def _load_run_track():
    return _load_module("tracking_run_track", TRACKING_BACKEND_ROOT / "cli.py")

def _load_target_crop():
    return _load_module("tracking_target_crop", TRACKING_BACKEND_ROOT / "crop.py")


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
        "core": summary,
        "front_view": "",
        "back_view": "",
        "distinguish": "",
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


def _session_state(frame_path: Path, latest_memory: object = "", latest_target_id: int | None = None) -> dict:
    payload = _session_payload(frame_path)
    payload.update(_memory_payload(latest_memory=latest_memory, latest_target_id=latest_target_id))
    return payload


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
    session_file.write_text(json.dumps(_session_state(frame_path)), encoding="utf-8")

    payload = select.execute_select_tool(
        session_file=session_file,
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
    session = _session_state(latest_frame_path)
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
    session["skill_cache"]["tracking"]["init_frame_snapshot"] = {
        "frame_id": "frame_000001",
        "timestamp_ms": 1710000000000,
        "image_path": str(first_frame_path),
        "detections": [
            {"track_id": 15, "bbox": [10, 12, 36, 44], "score": 0.95},
        ],
    }
    session_file.write_text(json.dumps(session), encoding="utf-8")

    payload = select.execute_select_tool(
        session_file=session_file,
        behavior="init",
        arguments={"target_description": "跟踪 ID 为 15 的人"},
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert payload["found"] is True


def test_select_target_init_uses_sub_model(tmp_path: Path, monkeypatch) -> None:
    select = _load_select()
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    session_file = tmp_path / "session.json"
    session = _session_state(frame_path)
    session["recent_frames"][0]["detections"] = [
        {"track_id": 15, "bbox": [10, 12, 36, 44], "score": 0.95},
    ]
    session_file.write_text(json.dumps(session), encoding="utf-8")

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
                    "bounding_box_id": 15,
                    "decision": "track",
                    "text": "已确认目标。",
                    "reason": "外观匹配。",
                    "reject_reason": "",
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
        behavior="init",
        arguments={"target_description": "穿黑衣服的人"},
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    assert payload["found"] is True
    assert len(calls) == 1
    assert calls[0]["model"] == "sub"
    assert payload["frame_id"] == "frame_000001"
    assert payload["target_id"] == 15


def test_select_target_requests_clarification_for_missing_explicit_id(tmp_path: Path) -> None:
    select = _load_select()
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps(_session_state(frame_path, latest_target_id=15)), encoding="utf-8")

    payload = select.execute_select_tool(
        session_file=session_file,
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
    session = _session_state(frame_path, latest_memory=_structured_memory("黑衣服，短发。"), latest_target_id=15)
    session["recent_frames"][0]["detections"] = [
        {"track_id": 42, "bbox": [8, 8, 36, 56], "score": 0.95},
        {"track_id": 16, "bbox": [48, 8, 78, 56], "score": 0.82},
    ]
    session["skill_cache"]["tracking"]["latest_confirmed_frame_path"] = str(reference_path)
    session["skill_cache"]["tracking"]["latest_confirmed_bbox"] = [8, 8, 36, 56]
    latest_target_crop = tmp_path / "latest_target_crop.jpg"
    Image.new("RGB", (28, 48), color=(20, 20, 20)).save(latest_target_crop, format="JPEG")
    latest_front_target_crop = tmp_path / "latest_front_target_crop.jpg"
    Image.new("RGB", (28, 48), color=(20, 20, 20)).save(latest_front_target_crop, format="JPEG")
    latest_back_target_crop = tmp_path / "latest_back_target_crop.jpg"
    Image.new("RGB", (28, 48), color=(30, 30, 30)).save(latest_back_target_crop, format="JPEG")
    session["skill_cache"]["tracking"]["latest_target_crop"] = str(latest_target_crop)
    session["skill_cache"]["tracking"]["identity_target_crop"] = str(latest_target_crop)
    session["skill_cache"]["tracking"]["latest_front_target_crop"] = str(latest_front_target_crop)
    session["skill_cache"]["tracking"]["latest_back_target_crop"] = str(latest_back_target_crop)
    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps(session), encoding="utf-8")

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
                    "decision": "track",
                    "text": "已确认继续跟踪 ID 42。",
                    "reason": "tracking memory 与 ID 42 的黑衣服和短发特征最一致。",
                    "reject_reason": "",
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
    assert len(calls[0]["image_paths"]) == 3
    assert str(latest_front_target_crop) == str(calls[0]["image_paths"][0])
    assert str(latest_back_target_crop) == str(calls[0]["image_paths"][1])
    assert str(calls[0]["image_paths"][2]).endswith("agent_artifacts/frame_000001_overlay.jpg")
    assert "tracking memory" in calls[0]["instruction"]
    assert "当前正面/背面参考 crop 说明" in calls[0]["instruction"]
    assert "当前候选框摘要" in calls[0]["instruction"]
    assert "先看正面/背面参考 crop，再看当前 overlay 图" in calls[0]["instruction"]
    assert "黑衣服，短发。" in calls[0]["instruction"]
    assert "默认按从下到上核验" in calls[0]["instruction"]
    assert "下半身特征已经足够稳定且没有明显冲突，可以直接 track" in calls[0]["instruction"]
    assert "不要依赖历史 ID、旧 ID" in calls[0]["instruction"]
    assert "如果当前候选像背影：优先用 back_view" in calls[0]["instruction"]


def test_select_target_track_survives_source_frame_cleanup(tmp_path: Path, monkeypatch) -> None:
    select = _load_select()
    frame_path = tmp_path / "frames" / "frame_000001.jpg"
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (96, 64), color="white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 36, 56), fill=(20, 20, 20))
    image.save(frame_path, format="JPEG")
    session = _session_state(frame_path, latest_memory=_structured_memory("黑衣服，短发。"), latest_target_id=15)
    session["recent_frames"][0]["detections"] = [{"track_id": 42, "bbox": [8, 8, 36, 56], "score": 0.95}]
    reference_path = _frame_image(tmp_path / "reference.jpg")
    session["skill_cache"]["tracking"]["latest_confirmed_frame_path"] = str(reference_path)
    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps(session), encoding="utf-8")

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
                    "decision": "track",
                    "text": "已确认继续跟踪 ID 42。",
                    "reason": "tracking memory 与 ID 42 的黑衣服和短发特征最一致。",
                    "reject_reason": "",
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
            "core": "黑色短袖T恤、卡其色短裤、白鞋白袜",
            "front_view": "正面短发，戴眼镜，黑色短袖T恤，卡其色短裤，白鞋白袜。",
            "back_view": "",
            "distinguish": "黑T配卡其短裤",
        },
        "latest_target_id": 54,
        "latest_confirmed_frame_path": str(reference_path),
        "latest_confirmed_bbox": [10, 12, 36, 44],
        "chat_history": [{"role": "user", "text": "继续跟踪", "timestamp": "t1"}],
        "recovery_mode": True,
        "missing_target_id": 54,
        "excluded_track_ids": [12, 41],
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
                    "decision": "ask",
                    "text": "请确认是不是 ID63。",
                    "reason": "当前只有一个候选，但下装看不清。",
                    "reject_reason": "",
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


def test_load_tracking_context_file_preserves_structured_memory_object(tmp_path: Path) -> None:
    select = _load_select()
    tracking_context = {
        "session_id": "sess_ctx",
        "target_description": "黑衣服的人",
        "memory": {
            "core": "黑色连帽外套、彩色鞋",
            "front_view": "正面可见左胸白色圆形 Logo。",
            "back_view": "",
            "distinguish": "和灰白鞋的人区分。",
        },
        "latest_target_id": 2,
        "excluded_track_ids": [3],
        "frames": [],
    }
    tracking_context_file = tmp_path / "tracking_context.json"
    tracking_context_file.write_text(json.dumps(tracking_context), encoding="utf-8")

    loaded = select.load_tracking_context_file(tracking_context_file)

    assert isinstance(loaded["memory"], dict)
    assert loaded["memory"]["core"] == "黑色连帽外套、彩色鞋"


def test_load_tracking_context_preserves_structured_memory_object(tmp_path: Path) -> None:
    select = _load_select()
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    session_state = _session_state(frame_path, latest_memory=_structured_memory("黑色连帽外套、彩色鞋"))
    session_state["recent_frames"][0]["detections"].append({"track_id": 21, "bbox": [14, 16, 30, 40], "score": 0.9})
    session_state["skill_cache"]["tracking"]["excluded_track_ids"] = [21]
    session_file = tmp_path / "session.json"
    session_file.write_text(
        json.dumps(session_state),
        encoding="utf-8",
    )

    loaded = select.load_tracking_context(session_file)

    assert isinstance(loaded["memory"], dict)
    assert loaded["memory"]["core"] == "黑色连帽外套、彩色鞋"
    assert loaded["excluded_track_ids"] == [21]
    assert [detection["track_id"] for detection in loaded["frames"][0]["detections"]] == [15, 16]


def test_select_target_track_rejects_model_target_not_in_current_candidates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    select = _load_select()
    frame_path = _frame_image(tmp_path / "frames" / "frame_000020.jpg")
    reference_path = _frame_image(tmp_path / "reference.jpg")
    tracking_context = {
        "session_id": "sess_001",
        "target_description": "黑衣服的人",
        "memory": {
            "core": "黑色连帽卫衣、左胸白色圆形 Logo、彩色鞋底",
            "front_view": "",
            "back_view": "",
            "distinguish": "",
        },
        "latest_target_id": 2,
        "latest_target_crop": str(tmp_path / "latest_target_crop.jpg"),
        "identity_target_crop": str(tmp_path / "identity_target_crop.jpg"),
        "latest_confirmed_frame_path": str(reference_path),
        "latest_confirmed_bbox": [10, 12, 36, 44],
        "chat_history": [{"role": "user", "text": "继续跟踪", "timestamp": "t1"}],
        "recovery_mode": True,
        "missing_target_id": 2,
        "excluded_track_ids": [7, 9],
        "frames": [
            {
                "frame_id": "frame_000020",
                "timestamp_ms": 1710000000000,
                "image_path": str(frame_path),
                "detections": [],
            }
        ],
    }
    tracking_context_file = tmp_path / "tracking_context.json"
    tracking_context_file.write_text(json.dumps(tracking_context), encoding="utf-8")

    _frame_image(Path(tracking_context["latest_target_crop"]))
    _frame_image(Path(tracking_context["identity_target_crop"]))

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
                    "found": True,
                    "bounding_box_id": 1,
                    "decision": "track",
                    "text": "已重新绑定目标（ID 1）。",
                    "reason": "左侧人物与历史目标最像。",
                    "reject_reason": "",
                    "needs_clarification": False,
                    "clarification_question": None,
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
    assert payload["target_id"] is None
    assert payload["rewrite_memory_input"] is None
    assert "不在当前候选列表中" in payload["reason"]


def test_select_target_track_recovers_unique_matched_candidate_when_model_returns_stale_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    select = _load_select()
    frame_path = _frame_image(tmp_path / "frames" / "frame_000021.jpg")
    reference_path = _frame_image(tmp_path / "reference.jpg")
    tracking_context = {
        "session_id": "sess_001",
        "target_description": "黑衣服的人",
        "memory": {
            "core": "黑色连帽卫衣、眼镜、浅灰色鞋",
            "front_view": "",
            "back_view": "",
            "distinguish": "",
        },
        "latest_target_id": 2,
        "latest_target_crop": str(tmp_path / "latest_target_crop.jpg"),
        "identity_target_crop": str(tmp_path / "identity_target_crop.jpg"),
        "latest_confirmed_frame_path": str(reference_path),
        "latest_confirmed_bbox": [10, 12, 36, 44],
        "chat_history": [{"role": "user", "text": "继续跟踪", "timestamp": "t1"}],
        "frames": [
            {
                "frame_id": "frame_000021",
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

    _frame_image(Path(tracking_context["latest_target_crop"]))
    _frame_image(Path(tracking_context["identity_target_crop"]))

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
                    "found": True,
                    "bounding_box_id": 5,
                    "decision": "track",
                    "text": "已切换为跟踪 ID 5 的目标。",
                    "reason": "当前候选与历史记忆一致。",
                    "reject_reason": "",
                    "needs_clarification": False,
                    "clarification_question": None,
                    "candidate_checks": [
                        {
                            "bounding_box_id": 63,
                            "status": "match",
                            "evidence": "黑色连帽卫衣、眼镜、浅灰色鞋一致。",
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

    assert payload["found"] is True
    assert payload["decision"] == "track"
    assert payload["target_id"] == 63
    assert payload["bounding_box_id"] == 63
    assert "唯一 match 的当前候选 ID 63" in payload["reason"]


def test_normalize_select_result_coerces_wait_to_unbound_state() -> None:
    select = _load_select()

    normalized = select.normalize_select_result(
        {
            "found": True,
            "bounding_box_id": 12,
            "decision": "wait",
            "text": "当前证据不足，保持等待。",
            "reason": "当前看不清关键特征。",
            "reject_reason": "当前看不清关键特征。",
            "needs_clarification": False,
            "clarification_question": None,
        }
    )

    assert normalized["found"] is False
    assert normalized["target_id"] is None
    assert normalized["bounding_box_id"] is None
    assert normalized["decision"] == "wait"


def test_normalize_select_result_uses_wait_reject_reason_as_reason_when_missing() -> None:
    select = _load_select()

    normalized = select.normalize_select_result(
        {
            "found": False,
            "bounding_box_id": None,
            "decision": "wait",
            "text": "当前证据不足，保持等待。",
            "reason": None,
            "reject_reason": "当前候选与记忆不一致。",
            "needs_clarification": False,
            "clarification_question": None,
        }
    )

    assert normalized["reason"] == "当前候选与记忆不一致。"
    assert normalized["reject_reason"] == "当前候选与记忆不一致。"


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
    session_file = tmp_path / "session.json"
    session_file.write_text(
        json.dumps(_session_state(frame_path, latest_memory=_structured_memory("旧记忆。"))),
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
                    "core": "黑色上衣、浅色裤子。",
                    "front_view": "正面黑色上衣、浅色裤子。",
                    "back_view": "",
                    "distinguish": "优先看黑色上衣和浅色裤子。",
                    "reference_view": "front",
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(rewrite, "load_settings", fake_settings)
    monkeypatch.setattr(rewrite, "call_model", fake_call_model)

    payload = rewrite.execute_rewrite_memory_tool(
        session_file=session_file,
        arguments={
            "task": "update",
            "crop_path": str(crop_path),
            "frame_paths": [str(frame_path)],
            "frame_id": "frame_000001",
            "target_id": 15,
            "confirmation_reason": "当前 crop 里的黑色上衣和浅色裤子与历史目标一致。",
            "candidate_checks": [
                {
                    "bounding_box_id": 15,
                    "status": "match",
                    "evidence": "黑色上衣、浅色裤子和整体体型一致。",
                }
            ],
        },
        env_file=tmp_path / ".ENV",
    )

    assert payload["task"] == "update"
    assert payload["target_id"] == 15
    assert payload["memory"]["core"] == "黑色上衣、浅色裤子。"
    assert payload["memory"]["front_view"] == "正面黑色上衣、浅色裤子。"
    assert payload["reference_view"] == "front"
    assert len(calls) == 1
    assert calls[0]["model"] == "sub"
    assert "core、front_view、back_view、distinguish、reference_view" in calls[0]["instruction"]
    assert "更新规则" in calls[0]["instruction"]
    assert "空字符串" in calls[0]["instruction"]
    assert "后续最容易混淆的人" in calls[0]["instruction"]
    assert "和周边最像的人如何区分" in calls[0]["instruction"]
    assert "位置、动作、姿态、手势、步态、朝向、bbox、轨迹 ID、确认状态都不能进入任何字段" in calls[0]["instruction"]
    assert "不要沿用旧场景描述" in calls[0]["instruction"]
    assert "保留已有 front_view" in calls[0]["instruction"]
    assert "front、back 或 unknown" in calls[0]["instruction"]
    assert "本轮成功确认理由" in calls[0]["instruction"]
    assert "本轮候选核验记录(JSON)" in calls[0]["instruction"]
    assert "黑色上衣和浅色裤子与历史目标一致" in calls[0]["instruction"]
    assert '"bounding_box_id": 15' in calls[0]["instruction"]


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
            "candidate_checks": [
                {"bounding_box_id": 15, "status": "match", "evidence": "外观一致"}
            ],
            "latest_target_crop": str(crop_path),
            "latest_front_target_crop": str(crop_path),
            "target_description": "黑衣服的人",
            "rewrite_memory_input": {
                "task": "update",
                "crop_path": str(crop_path),
                "frame_paths": [str(frame_path)],
                "frame_id": "frame_000001",
                "target_id": 15,
                "confirmation_reason": "外观一致",
                "candidate_checks": [
                    {"bounding_box_id": 15, "status": "match", "evidence": "外观一致"}
                ],
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
    assert payload["rewrite_memory_input"]["confirmation_reason"] == "外观一致"


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
            "reject_reason": "候选 ID 15 的上衣相近，但下装和鞋子都看不清，当前无法稳定确认。",
            "target_description": "黑衣服的人",
        }
    )

    assert payload["session_result"]["decision"] == "wait"
    assert "原因：" in payload["session_result"]["text"]
    assert "下装和鞋子都看不清" in payload["session_result"]["text"]
    assert payload["skill_state_patch"]["pending_question"] is None
    assert payload["robot_response"]["action"] == "wait"
    assert "原因：" in payload["robot_response"]["text"]


def test_turn_payload_resets_view_specific_reference_crops_for_new_target(tmp_path: Path) -> None:
    payload_module = _load_turn_payload()
    runtime = AgentSessionStore(tmp_path / "state")
    runtime.patch_skill_state(
        "sess_reset",
        skill_name="tracking",
        patch={
            "latest_front_target_crop": "/old/front.jpg",
            "latest_back_target_crop": "/old/back.jpg",
        },
    )

    payload = payload_module.build_tracking_turn_payload(
        {
            "behavior": "init",
            "frame_id": "frame_000020",
            "target_id": 99,
            "bounding_box_id": 99,
            "found": True,
            "decision": "track",
            "text": "已确认新目标。",
            "reason": "direct init",
            "reset_reference_crops": True,
            "target_description": "新目标",
        }
    )

    runtime.patch_skill_state(
        "sess_reset",
        skill_name="tracking",
        patch=payload["skill_state_patch"],
    )

    tracking_state = runtime.load("sess_reset").skill_cache["tracking"]
    assert payload["skill_state_patch"]["latest_front_target_crop"] is None
    assert payload["skill_state_patch"]["latest_back_target_crop"] is None
    assert tracking_state["latest_front_target_crop"] is None
    assert tracking_state["latest_back_target_crop"] is None


def test_normalize_select_result_keeps_literal_string_clarification_question(tmp_path: Path) -> None:
    select = _load_select()

    payload = select.normalize_select_result(
        {
            "found": True,
            "bounding_box_id": 2,
            "text": "已确认目标。",
            "reason": "ok",
            "clarification_question": "None",
            "decision": "track",
        }
    )

    assert payload["clarification_question"] == "None"


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
            "tracking_cli.py",
            "track",
            "--session-file",
            str(tmp_path / "session.json"),
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


def test_schedule_tracking_memory_rewrite_updates_session_inline(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    runtime = AgentSessionStore(state_root=state_root)
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
    )
    runtime.apply_skill_result(
        "sess_worker",
        {"behavior": "track", "frame_id": "frame_000001", "target_id": 15, "found": True, "text": "继续跟踪"},
    )
    runtime.patch_skill_state(
        "sess_worker",
        skill_name="tracking",
        patch={
            "latest_target_id": 15,
            "latest_confirmed_frame_path": str(frame_path),
        },
    )
    monkeypatch.setattr(
        "backend.tracking.deterministic.execute_rewrite_memory_tool",
        lambda **_: {
            "task": "update",
            "memory": _structured_memory("新的 memory"),
            "frame_id": "frame_000001",
            "target_id": 15,
            "crop_path": str(crop_path),
            "reference_view": "front",
            "elapsed_seconds": 0.05,
        },
    )

    schedule_tracking_memory_rewrite(
        sessions=runtime,
        session_id="sess_worker",
        rewrite_memory_input={
            "task": "update",
            "crop_path": str(crop_path),
            "frame_paths": [str(frame_path)],
            "frame_id": "frame_000001",
            "target_id": 15,
        },
        env_file=tmp_path / ".ENV",
    )

    context = runtime.load("sess_worker")
    assert context.skill_cache["tracking"]["latest_memory"] == _structured_memory("新的 memory")
    assert context.skill_cache["tracking"]["latest_front_target_crop"] == str(crop_path)


def test_schedule_tracking_memory_rewrite_skips_superseded_state(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    runtime = AgentSessionStore(state_root=state_root)
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
    )
    runtime.apply_skill_result(
        "sess_worker_skip",
        {"behavior": "track", "frame_id": "frame_000001", "target_id": 15, "found": True, "text": "继续跟踪"},
    )
    runtime.patch_skill_state(
        "sess_worker_skip",
        skill_name="tracking",
        patch={
            "latest_target_id": 99,
            "latest_confirmed_frame_path": str(tmp_path / "other_frame.jpg"),
            "latest_memory": _structured_memory("旧 memory"),
        },
    )
    monkeypatch.setattr(
        "backend.tracking.deterministic.execute_rewrite_memory_tool",
        lambda **_: (_ for _ in ()).throw(AssertionError("superseded rewrite should not execute")),
    )

    schedule_tracking_memory_rewrite(
        sessions=runtime,
        session_id="sess_worker_skip",
        rewrite_memory_input={
            "task": "update",
            "crop_path": str(crop_path),
            "frame_paths": [str(frame_path)],
            "frame_id": "frame_000001",
            "target_id": 15,
        },
        env_file=tmp_path / ".ENV",
    )

    context = runtime.load("sess_worker_skip")
    assert context.skill_cache["tracking"]["latest_memory"] == _structured_memory("旧 memory")


def test_select_init_requests_clarification_when_multiple_candidates_match(tmp_path: Path, monkeypatch):
    """Test that init mode asks for clarification when multiple candidates match the description."""
    select = _load_select()

    from backend.config import Settings

    def fake_settings(_: Path | None = None):
        return Settings(
            api_key="test",
            base_url="http://test",
            model="main",
            main_model="main",
            sub_model="sub",
            timeout_seconds=30,
            sample_fps=1.0,
            query_interval_seconds=3,
            recent_frame_count=3,
            chat_model="chat",
        )

    # 模拟模型返回多个匹配的候选
    def fake_call_model(**kwargs):
        return {
            "elapsed_seconds": 0.05,
            "response_text": json.dumps(
                {
                    "found": True,
                    "bounding_box_id": 10,
                    "decision": "track",
                    "text": "已锁定穿黑衣服的人。",
                    "reason": "找到匹配的候选人。",
                    "reject_reason": "",
                    "needs_clarification": False,
                    "clarification_question": None,
                    "candidate_checks": [
                        {"bounding_box_id": 10, "status": "match", "evidence": "黑色上衣、浅色短裤"},
                        {"bounding_box_id": 11, "status": "match", "evidence": "黑色上衣、深色长裤"},
                    ],
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(select, "load_settings", fake_settings)
    monkeypatch.setattr(select, "call_model", fake_call_model)

    # 创建测试用的 session 文件
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    session_file = tmp_path / "session.json"
    session = {
        "session_id": "test_session",
        "device_id": "robot_01",
        "latest_request_id": "req_001",
        "latest_request_function": "chat",
        "conversation_history": [],
        "recent_frames": [
            {
                "frame_id": "frame_000001",
                "timestamp_ms": 1710000000000,
                "image_path": str(frame_path),
                "detections": [
                    {"track_id": 10, "bbox": [100, 100, 200, 300], "score": 0.92},
                    {"track_id": 11, "bbox": [300, 100, 400, 300], "score": 0.89},
                ],
            }
        ],
        "user_preferences": {},
        "environment_map": {},
        "perception_cache": {},
        "skill_cache": {
            "tracking": {
                "target_description": "穿黑衣服的人",
                "latest_memory": "",
                "latest_target_id": None,
                "latest_confirmed_frame_path": None,
            }
        },
    }
    session_file.write_text(json.dumps(session), encoding="utf-8")

    result = select.execute_select_tool(
        session_file=session_file,
        behavior="init",
        arguments={"target_description": "穿黑衣服的人"},
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    # 验证结果：应该触发澄清问题，而不是直接锁定目标
    assert result["found"] is False
    assert result["decision"] == "ask"
    assert result["needs_clarification"] is True
    assert result["target_id"] is None
    assert result["bounding_box_id"] is None
    assert "2 个匹配的目标" in result["text"]
    assert "ID 10" in result["text"]
    assert "ID 11" in result["text"]
    assert "黑色上衣、浅色短裤" in result["text"]
    assert "黑色上衣、深色长裤" in result["text"]


def test_select_init_does_not_request_clarification_when_single_match(tmp_path: Path, monkeypatch):
    """Test that init mode proceeds normally when only one candidate matches."""
    select = _load_select()

    from backend.config import Settings

    def fake_settings(_: Path | None = None):
        return Settings(
            api_key="test",
            base_url="http://test",
            model="main",
            main_model="main",
            sub_model="sub",
            timeout_seconds=30,
            sample_fps=1.0,
            query_interval_seconds=3,
            recent_frame_count=3,
            chat_model="chat",
        )

    # 模拟模型返回单个匹配的候选
    def fake_call_model(**kwargs):
        return {
            "elapsed_seconds": 0.05,
            "response_text": json.dumps(
                {
                    "found": True,
                    "bounding_box_id": 10,
                    "decision": "track",
                    "text": "已锁定穿黑衣服的人。",
                    "reason": "找到唯一匹配的候选人。",
                    "reject_reason": "",
                    "needs_clarification": False,
                    "clarification_question": None,
                    "candidate_checks": [
                        {"bounding_box_id": 10, "status": "match", "evidence": "黑色上衣、浅色短裤"},
                        {"bounding_box_id": 11, "status": "unknown", "evidence": "上衣颜色不符"},
                    ],
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(select, "load_settings", fake_settings)
    monkeypatch.setattr(select, "call_model", fake_call_model)

    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    session_file = tmp_path / "session.json"
    session = {
        "session_id": "test_session",
        "device_id": "robot_01",
        "latest_request_id": "req_001",
        "latest_request_function": "chat",
        "conversation_history": [],
        "recent_frames": [
            {
                "frame_id": "frame_000001",
                "timestamp_ms": 1710000000000,
                "image_path": str(frame_path),
                "detections": [
                    {"track_id": 10, "bbox": [100, 100, 200, 300], "score": 0.92},
                    {"track_id": 11, "bbox": [300, 100, 400, 300], "score": 0.89},
                ],
            }
        ],
        "user_preferences": {},
        "environment_map": {},
        "perception_cache": {},
        "skill_cache": {
            "tracking": {
                "target_description": "穿黑衣服的人",
                "latest_memory": "",
                "latest_target_id": None,
                "latest_confirmed_frame_path": None,
            }
        },
    }
    session_file.write_text(json.dumps(session), encoding="utf-8")

    result = select.execute_select_tool(
        session_file=session_file,
        behavior="init",
        arguments={"target_description": "穿黑衣服的人"},
        env_file=tmp_path / ".ENV",
        artifacts_root=tmp_path / "artifacts",
    )

    # 验证结果：应该直接锁定目标，不触发澄清问题
    assert result["found"] is True
    assert result["decision"] == "track"
    assert result["needs_clarification"] is False
    assert result["target_id"] == 10
