from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRACKING_SKILL_ROOT = ROOT / "skills" / "tracking"


def _load_config() -> dict:
    path = TRACKING_SKILL_ROOT / "references" / "robot-agent-config.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_memory_prompts_prioritize_detailed_appearance_and_avoid_actions() -> None:
    config = _load_config()
    init_prompt = str(config["prompts"]["memory_init_prompt"])
    optimize_prompt = str(config["prompts"]["memory_optimize_prompt"])

    for prompt in (init_prompt, optimize_prompt):
        assert "JSON" in prompt
        assert "head_face" in prompt
        assert "upper_body" in prompt
        assert "lower_body" in prompt
        assert "shoes" in prompt
        assert "distinguish" in prompt
        assert "summary" in prompt
        assert "稳定外观" in prompt or "稳定特征" in prompt
        assert "相似人A" in prompt
        assert "只写目标自己" in prompt or "summary：只写目标自己" in prompt
        assert "不要写相似人" in prompt
        assert "当前最近邻相似人" in prompt
        assert ("只要当前帧里确实有一个" in prompt or "只要当前帧里确实有这样一个人" in prompt)
        assert ("如果当前帧只有目标" in prompt or "如果当前帧没有这样的相似人" in prompt or "就写空字符串" in prompt)
        assert "空字符串" in prompt
        assert "位置词" in prompt
        assert ("前景/背景" in prompt or "前景" in prompt)
        assert ("远近" in prompt or "走廊" in prompt)
        assert ("快走慢走" in prompt or "动作" in prompt)
        assert ("不沿用旧场景" in prompt or "位置和动作会变" in prompt)
        assert "动作、位置、bbox、确认、匹配" in prompt
        assert "身份特征" in prompt

    assert "初始化 tracking memory" in init_prompt
    assert "已有 tracking memory" in optimize_prompt
    assert "沿用旧值" in optimize_prompt


def test_select_prompts_prefer_stable_appearance_for_hard_cases() -> None:
    config = _load_config()
    init_prompt = str(config["prompts"]["init_skill_prompt"])
    track_prompt = str(config["prompts"]["track_skill_prompt"])

    assert "hard case" in init_prompt
    assert "稳定外观细节" in init_prompt
    assert "不能依赖单一特征" in init_prompt
    assert "不要把动作" in init_prompt

    assert "hard case" in track_prompt
    assert "身份连续性" in track_prompt
    assert "可迁移" in track_prompt
    assert "unknown" in track_prompt
    assert "位置、左右、前景、背景" in track_prompt
    assert "不能单独用来认人" in track_prompt
    assert "绝不能当成正证据" in track_prompt
    assert "默认等待原目标重新出现" in track_prompt
    assert "若候选只是在位置上合理" in track_prompt


def test_memory_optimize_prompt_uses_existing_memory_context() -> None:
    config = _load_config()
    optimize_prompt = str(config["prompts"]["memory_optimize_prompt"])
    memory_contract = str(config["contracts"]["memory_json"])

    assert "{current_memory}" in optimize_prompt
    assert "当前 tracking memory(JSON)" in optimize_prompt
    assert '"appearance"' in memory_contract
    assert '"summary"' in memory_contract
