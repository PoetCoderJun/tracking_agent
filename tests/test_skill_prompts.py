from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "vision-tracking-skill"


def _load_config(name: str) -> dict:
    path = SKILL_ROOT / "references" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_memory_prompts_prioritize_detailed_appearance_and_avoid_actions() -> None:
    for name in ("agent-config.json", "robot-agent-config.json"):
        config = _load_config(name)
        init_prompt = str(config["prompts"]["memory_init_prompt"])
        optimize_prompt = str(config["prompts"]["memory_optimize_prompt"])

        for prompt in (init_prompt, optimize_prompt):
            assert "不要为了简短而缩写" in prompt or "不要为了压缩篇幅而把已有细节缩写掉" in prompt
            assert "从上到下" in prompt
            assert "脸型" in prompt
            assert "鞋底" in prompt
            assert "包带" in prompt
            assert "只拍到半身" in prompt or "只露出半身" in prompt
            assert "单一特征" in prompt
            assert "低机位" in prompt or "局部可见" in prompt
            assert "不要把动作" in prompt or "不要把动作、姿态" in prompt


def test_select_prompts_prefer_stable_appearance_for_hard_cases() -> None:
    for name in ("agent-config.json", "robot-agent-config.json"):
        config = _load_config(name)
        init_prompt = str(config["prompts"]["init_skill_prompt"])
        track_prompt = str(config["prompts"]["track_skill_prompt"])

        assert "hard case" in init_prompt
        assert "稳定外观细节" in init_prompt
        assert "不能依赖单一特征" in init_prompt
        assert "不要把动作" in init_prompt

        assert "hard case" in track_prompt
        assert "可见脸部特征" in track_prompt
        assert "不能依赖单一特征" in track_prompt
        assert "unknown" in track_prompt
        assert "不要轻易切换到旁边相似的人" in track_prompt
        assert "不要用动作" in track_prompt


def test_memory_optimize_prompt_uses_existing_memory_context() -> None:
    for name in ("agent-config.json", "robot-agent-config.json"):
        config = _load_config(name)
        optimize_prompt = str(config["prompts"]["memory_optimize_prompt"])
        memory_contract = str(config["contracts"]["memory_markdown"])

        assert "{current_memory}" in optimize_prompt
        assert "当前 tracking memory" in optimize_prompt
        assert "不要为了简短而缩写 memory" in memory_contract
