from __future__ import annotations

from pathlib import Path

from backend.config import load_settings


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
    assert settings.chat_model == "qwen3.5-flash"


def test_load_settings_prefers_explicit_main_model(tmp_path: Path) -> None:
    env_path = tmp_path / ".ENV"
    env_path.write_text(
        "\n".join(
            [
                "DASHSCOPE_MODEL=qwen-vl-plus-latest",
                "DASHSCOPE_MAIN_MODEL=qwen3.5-plus",
                "DASHSCOPE_SUB_MODEL=qwen3.5-plus",
                "DASHSCOPE_CHAT_MODEL=qwen3.5-flash",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env_path)

    assert settings.main_model == "qwen3.5-plus"
    assert settings.sub_model == "qwen3.5-plus"
    assert settings.chat_model == "qwen3.5-flash"


def test_project_declares_lap_for_bytetrack_runtime() -> None:
    root = Path(__file__).resolve().parents[2]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")

    assert '"lap>=0.5.12"' in pyproject
    assert "lap>=0.5.12" in requirements
