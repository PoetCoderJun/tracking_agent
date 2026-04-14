from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from capabilities.tracking.policy.prompt_templates import (
    TRACKING_MEMORY_INIT_PROMPT_PATH,
    TRACKING_MEMORY_UPDATE_PROMPT_PATH,
    render_prompt_template,
)
from capabilities.tracking.policy.rewrite_memory import execute_rewrite_memory_tool


def _image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def test_execute_rewrite_memory_tool_uses_flash_model(tmp_path: Path, monkeypatch) -> None:
    state_root = tmp_path / "state"
    session_file = state_root / "sessions" / "sess_tracking" / "session.json"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(json.dumps({"session_id": "sess_tracking"}, ensure_ascii=True), encoding="utf-8")

    crop_path = _image(tmp_path / "crop.jpg")
    frame_path = _image(tmp_path / "frame.jpg")
    requested_models: list[str] = []

    monkeypatch.setattr(
        "capabilities.tracking.policy.rewrite_memory.load_settings",
        lambda _env_file: SimpleNamespace(
            api_key="test-key",
            base_url="https://example.com",
            timeout_seconds=10,
            model="qwen3.6-plus",
            main_model="qwen3.6-plus",
            sub_model="qwen3.6-plus",
            chat_model="qwen3.5-flash",
        ),
    )

    def _fake_call_model(**kwargs):
        requested_models.append(str(kwargs["model"]))
        return {
            "elapsed_seconds": 0.01,
            "response_text": json.dumps(
                {
                    "core": "黑色上衣，浅色裤子，白色鞋底。",
                    "front_view": "",
                    "back_view": "",
                    "distinguish": "",
                    "reference_view": "unknown",
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr("capabilities.tracking.policy.rewrite_memory.call_model", _fake_call_model)

    payload = execute_rewrite_memory_tool(
        session_file=session_file,
        arguments={
            "task": "init",
            "crop_path": str(crop_path),
            "frame_paths": [str(frame_path)],
            "frame_id": "frame_000001",
            "target_id": 15,
        },
        env_file=tmp_path / ".ENV",
    )

    assert requested_models == ["qwen3.5-flash"]
    assert payload["memory"]["core"] == "黑色上衣，浅色裤子，白色鞋底。"


def test_tracking_memory_prompts_live_under_runtime_capability() -> None:
    assert TRACKING_MEMORY_INIT_PROMPT_PATH.exists()
    assert TRACKING_MEMORY_UPDATE_PROMPT_PATH.exists()
    assert "capabilities/tracking/" in str(TRACKING_MEMORY_INIT_PROMPT_PATH)
    assert "capabilities/tracking/" in str(TRACKING_MEMORY_UPDATE_PROMPT_PATH)


def test_tracking_memory_update_prompt_does_not_require_confirmation_reason() -> None:
    prompt = render_prompt_template(
        prompt_key="tracking_memory_update_prompt",
        current_memory="{}",
        candidate_checks="[]",
    )

    assert "{confirmation_reason}" not in prompt
    assert "confirmation_reason" not in prompt
