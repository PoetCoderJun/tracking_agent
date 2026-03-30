from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

from PIL import Image

from backend.config import Settings


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


def _memory_payload(latest_memory: str = "", latest_target_id: int | None = None) -> dict:
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


def test_select_target_uses_model_when_description_is_implicit(tmp_path: Path, monkeypatch) -> None:
    select = _load_select()
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    reference_path = _frame_image(tmp_path / "reference.jpg")
    session = _session_payload(frame_path)
    memory = _memory_payload(latest_memory="黑衣服，短发。", latest_target_id=15)
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

    calls: list[dict[str, object]] = []

    def fake_call_model(**kwargs):
        calls.append(kwargs)
        return {
            "elapsed_seconds": 0.05,
            "response_text": '{"found": true, "bounding_box_id": 15, "text": "继续跟踪当前目标。", "reason": "外观一致", "needs_clarification": false, "clarification_question": null}',
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
    assert payload["target_id"] == 15
    assert payload["rewrite_memory_input"]["task"] == "update"
    assert len(calls) == 1
    assert calls[0]["model"] == "main"


def test_rewrite_memory_uses_sub_model_and_normalizes_memory(tmp_path: Path, monkeypatch) -> None:
    rewrite = _load_rewrite()
    crop_path = _frame_image(tmp_path / "crops" / "target.jpg")
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    memory_file = tmp_path / "agent_memory.json"
    memory_file.write_text(
        json.dumps(_memory_payload(latest_memory="旧记忆。")),
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
            "response_text": "更新后的 tracking memory",
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
    assert payload["memory"].startswith("# Tracking Memory")
    assert "更新后的 tracking memory" in payload["memory"]
    assert len(calls) == 1
    assert calls[0]["model"] == "sub"
