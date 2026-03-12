from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = ROOT / "skills" / "vision-tracking-skill" / "scripts" / "pi_backend_bridge.py"


def _load_bridge():
    spec = importlib.util.spec_from_file_location("vision_tracking_pi_backend_bridge", BRIDGE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load bridge module from {BRIDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_backend_result_payload_maps_adapter_output() -> None:
    bridge = _load_bridge()

    payload = bridge.backend_result_payload(
        {
            "behavior": "track",
            "text": "继续跟踪当前目标。",
            "target_id": 12,
            "found": True,
            "needs_clarification": False,
            "clarification_question": None,
            "memory": "短发，黑衣服。",
            "target_description": "黑衣服的人",
            "pending_question": None,
            "latest_target_crop": "/tmp/crop.jpg",
        }
    )

    assert payload["behavior"] == "track"
    assert payload["target_id"] == 12
    assert payload["bounding_box_id"] == 12
    assert payload["latest_target_crop"] == "/tmp/crop.jpg"


def test_run_bridge_posts_result_and_applies_memory_rewrite(tmp_path: Path, monkeypatch) -> None:
    bridge = _load_bridge()

    context_payload = {
        "session_id": "sess_001",
        "memory": "",
        "latest_target_id": None,
        "frames": [],
    }
    posted: list[dict[str, object]] = []

    def fake_fetch_json(url: str):
        assert url.endswith("/api/v1/sessions/sess_001/agent-context")
        return context_payload

    def fake_post_json(url: str, payload: dict):
        posted.append({"url": url, "payload": payload})
        return {"session_id": "sess_001", "latest_memory": payload["memory"]}

    def fake_execute_tool(*, tool_name, context, arguments, env_file, config_path, artifacts_root):
        if tool_name == "track":
            return {
                "behavior": "track",
                "text": "已继续跟踪。",
                "target_id": 15,
                "found": True,
                "needs_clarification": False,
                "clarification_question": None,
                "memory": "",
                "target_description": "黑衣服的人",
                "pending_question": None,
                "latest_target_crop": str(tmp_path / "crop.jpg"),
                "rewrite_memory_input": {
                    "task": "update",
                    "crop_path": str(tmp_path / "crop.jpg"),
                    "frame_paths": [str(tmp_path / "frame.jpg")],
                    "frame_id": "frame_000001",
                    "target_id": 15,
                },
            }
        if tool_name == "rewrite_memory":
            return {
                "task": "update",
                "memory": "更新后的 memory",
                "frame_id": "frame_000001",
                "target_id": 15,
                "crop_path": str(tmp_path / "crop.jpg"),
            }
        raise AssertionError(f"Unexpected tool invocation: {tool_name}")

    monkeypatch.setattr(bridge, "fetch_json", fake_fetch_json)
    monkeypatch.setattr(bridge, "post_json", fake_post_json)
    monkeypatch.setattr(bridge.adapter, "execute_tool", fake_execute_tool)

    result = bridge.run_bridge(
        backend_base_url="http://127.0.0.1:8001",
        session_id="sess_001",
        tool_name="track",
        arguments={},
        env_file=tmp_path / ".ENV",
        config_path=bridge.adapter.DEFAULT_CONFIG_PATH,
        artifacts_root=tmp_path / "pi-agent",
        skip_rewrite_memory=False,
        dry_run=False,
    )

    assert result["rewrite_output"]["memory"] == "更新后的 memory"
    assert result["posted_payload"]["memory"] == "更新后的 memory"
    assert posted[0]["url"].endswith("/api/v1/sessions/sess_001/agent-result")


def test_run_bridge_supports_dry_run(tmp_path: Path, monkeypatch) -> None:
    bridge = _load_bridge()

    monkeypatch.setattr(bridge, "fetch_json", lambda url: {"session_id": "sess_001", "frames": []})
    monkeypatch.setattr(
        bridge.adapter,
        "execute_tool",
        lambda **kwargs: {
            "behavior": "reply",
            "text": "请再描述一下目标。",
            "target_id": None,
            "found": False,
            "needs_clarification": True,
            "clarification_question": "请再描述一下目标。",
            "memory": "",
            "pending_question": "请再描述一下目标。",
        },
    )

    result = bridge.run_bridge(
        backend_base_url="http://127.0.0.1:8001",
        session_id="sess_001",
        tool_name="reply",
        arguments={"text": "请再描述一下目标。"},
        env_file=tmp_path / ".ENV",
        config_path=bridge.adapter.DEFAULT_CONFIG_PATH,
        artifacts_root=tmp_path / "pi-agent",
        skip_rewrite_memory=True,
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["posted_result"] is None
    assert result["posted_payload"]["behavior"] == "reply"
