from __future__ import annotations

from pathlib import Path

from tracking_agent.config import load_settings


def test_load_settings_defaults_models_to_qwen35_family(tmp_path: Path) -> None:
    env_path = tmp_path / ".ENV"
    env_path.write_text(
        "\n".join(
            [
                "DASHSCOPE_MODEL=qwen3.5-plus",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env_path)

    assert settings.main_model == "qwen3.5-plus"
    assert settings.sub_model == "qwen3.5-flash"


def test_load_settings_prefers_explicit_main_model(tmp_path: Path) -> None:
    env_path = tmp_path / ".ENV"
    env_path.write_text(
        "\n".join(
            [
                "DASHSCOPE_MODEL=qwen-vl-plus-latest",
                "DASHSCOPE_MAIN_MODEL=qwen3.5-plus",
                "DASHSCOPE_SUB_MODEL=qwen3.5-plus",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env_path)

    assert settings.main_model == "qwen3.5-plus"
    assert settings.sub_model == "qwen3.5-plus"
