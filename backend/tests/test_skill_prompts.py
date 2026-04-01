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
        assert "core" in prompt
        assert "front_view" in prompt
        assert "back_view" in prompt
        assert "distinguish" in prompt
        assert "reference_view" in prompt
        assert "尽量从上到下连续描述尽量多的细节特征" in prompt
        assert "当前画面里确实有一个与目标存在相似之处" in prompt
        assert "如果当前没有明显相似人，就写空字符串" in prompt
        assert "相似人A" in prompt
        assert "两者都" in prompt
        assert "A 的" in prompt
        assert "目标的" in prompt
        assert "可以通过" in prompt
        assert "不要写“目标区别" in prompt or "不要写“目标区别：……”" in prompt
        assert "空字符串" in prompt
        assert "位置和动作会变" in prompt
        assert "不写位置和动作" in prompt
        assert "姿态、手部状态、步态" in prompt
        assert "是否插兜" in prompt
        assert "distinguish 只能使用稳定外观特征" in prompt
        assert "上衣、裤子、鞋子、配饰、发型、体型等所有稳定特征" in prompt
        assert "不要只写颜色和大类" in prompt
        assert "版型、层次、材质感、图案或 logo、边缘/收口、长度、厚薄、拼色、磨损、包带或挂件" in prompt
        assert "身份特征" in prompt
        assert "front、back 或 unknown" in prompt

    assert "初始化 tracking memory" in init_prompt
    assert "已有 tracking memory" in optimize_prompt
    assert "保留已有 front_view" in optimize_prompt
    assert "保留已有 back_view" in optimize_prompt


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
    assert "正面或背面参考 crop" in track_prompt
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
    assert '"core"' in memory_contract
    assert '"front_view"' in memory_contract
    assert '"back_view"' in memory_contract
    assert '"reference_view"' in memory_contract
