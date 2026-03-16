from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from PIL import Image

from tracking_agent.config import Settings


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "skills" / "vision-tracking-skill" / "scripts" / "pi_agent_adapter.py"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("vision_tracking_pi_agent_adapter", ADAPTER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load adapter module from {ADAPTER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def test_describe_tools_exposes_manifest() -> None:
    adapter = _load_adapter()

    manifest = adapter.describe_tools(adapter.DEFAULT_TOOLS_PATH)

    assert manifest["skill_name"] == "vision-tracking-skill"
    assert any(tool["name"] == "track" for tool in manifest["tools"])


def test_execute_reply_tool_formats_backend_payload() -> None:
    adapter = _load_adapter()
    context = {
        "session_id": "sess_001",
        "memory": "黑衣服，短发。",
        "latest_target_id": 15,
        "latest_result": {"found": True},
    }

    payload = adapter.execute_reply_tool(
        context,
        {
            "text": "我还在跟踪同一个人。",
            "needs_clarification": True,
            "clarification_question": "你说的是左边那个还是中间那个？",
        },
    )

    assert payload["behavior"] == "reply"
    assert payload["frame_id"] is None
    assert payload["target_id"] == 15
    assert payload["pending_question"] == "你说的是左边那个还是中间那个？"


def test_build_working_context_shapes_raw_backend_session() -> None:
    adapter = _load_adapter()

    context = adapter.build_working_context(
        {
            "session_id": "sess_001",
            "device_id": "robot_01",
            "target_description": "黑衣服的人",
            "latest_memory": "黑衣服，短发。",
            "latest_target_id": 15,
            "latest_target_crop": "/tmp/crop.jpg",
            "latest_confirmed_frame_path": "/tmp/frame.jpg",
            "latest_result": {
                "behavior": "track",
                "text": "继续跟踪。",
                "target_id": 15,
                "found": True,
            },
            "clarification_notes": [],
            "conversation_history": [{"role": "user", "text": "继续跟踪", "timestamp": "t1"}],
            "pending_question": None,
            "recent_frames": [
                {
                    "frame_id": "frame_000001",
                    "timestamp_ms": 1710000000000,
                    "image_path": "/tmp/frame.jpg",
                    "detections": [
                        {"track_id": 15, "bbox": [10, 12, 36, 44], "score": 0.95},
                    ],
                }
            ],
            "created_at": "t0",
            "updated_at": "t1",
        }
    )

    assert context["memory"] == "黑衣服，短发。"
    assert context["latest_bounding_box_id"] == 15
    assert context["latest_result"]["bounding_box_id"] == 15
    assert context["frames"][-1]["detections"][0]["bounding_box_id"] == 15


def test_execute_init_tool_returns_rewrite_memory_input(tmp_path: Path, monkeypatch) -> None:
    adapter = _load_adapter()
    frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")

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
        )

    calls: list[dict[str, object]] = []

    def fake_call_model(**kwargs):
        calls.append(kwargs)
        return {
            "elapsed_seconds": 0.12,
            "response_text": '{"found": true, "target_id": 15, "text": "已确认目标", "needs_clarification": false, "reason": ""}',
        }

    monkeypatch.setattr(adapter, "load_settings", fake_settings)
    monkeypatch.setattr(adapter, "call_model", fake_call_model)

    context = {
        "session_id": "sess_001",
        "target_description": "",
        "memory": "",
        "latest_target_id": None,
        "latest_confirmed_frame_path": None,
        "conversation_history": [],
        "latest_result": None,
        "frames": [
            {
                "frame_id": "frame_000001",
                "timestamp_ms": 1710000000000,
                "image_path": str(frame_path),
                "detections": [
                    {"track_id": 15, "bbox": [10, 12, 36, 44], "score": 0.95},
                ],
            }
        ],
    }

    payload = adapter.execute_tool(
        tool_name="init",
        context=context,
        arguments={"target_description": "穿黑衣服的人"},
        env_file=tmp_path / ".ENV",
        config_path=adapter.DEFAULT_CONFIG_PATH,
        artifacts_root=tmp_path / "pi-agent",
    )

    assert len(calls) == 1
    assert payload["behavior"] == "init"
    assert payload["frame_id"] == "frame_000001"
    assert payload["found"] is True
    assert payload["target_id"] == 15
    assert payload["rewrite_memory_input"]["task"] == "init"
    assert payload["rewrite_memory_input"]["frame_paths"] == [str(frame_path)]
    assert Path(payload["latest_target_crop"]).exists()


def test_execute_track_tool_rewrite_memory_uses_previous_and_current_success_frames(tmp_path: Path, monkeypatch) -> None:
    adapter = _load_adapter()
    previous_frame_path = _frame_image(tmp_path / "frames" / "frame_000001.jpg")
    current_frame_path = _frame_image(tmp_path / "frames" / "frame_000002.jpg")

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
        )

    def fake_call_model(**kwargs):
        return {
            "elapsed_seconds": 0.12,
            "response_text": '{"found": true, "target_id": 15, "text": "已继续跟踪", "needs_clarification": false, "reason": ""}',
        }

    monkeypatch.setattr(adapter, "load_settings", fake_settings)
    monkeypatch.setattr(adapter, "call_model", fake_call_model)

    context = {
        "session_id": "sess_001",
        "target_description": "穿黑衣服的人",
        "memory": "黑衣服，短发。",
        "latest_target_id": 15,
        "latest_confirmed_frame_path": str(previous_frame_path),
        "conversation_history": [],
        "latest_result": {
            "frame_id": "frame_000001",
            "target_id": 15,
            "found": True,
        },
        "frames": [
            {
                "frame_id": "frame_000002",
                "timestamp_ms": 1710000003000,
                "image_path": str(current_frame_path),
                "detections": [
                    {"track_id": 15, "bbox": [10, 12, 36, 44], "score": 0.95},
                ],
            }
        ],
    }

    payload = adapter.execute_tool(
        tool_name="track",
        context=context,
        arguments={"user_text": "持续跟踪"},
        env_file=tmp_path / ".ENV",
        config_path=adapter.DEFAULT_CONFIG_PATH,
        artifacts_root=tmp_path / "pi-agent",
    )

    assert payload["behavior"] == "track"
    assert payload["rewrite_memory_input"]["task"] == "update"
    assert payload["rewrite_memory_input"]["frame_paths"] == [
        str(previous_frame_path),
        str(current_frame_path),
    ]
