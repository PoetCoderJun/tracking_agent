from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRACKING_BACKEND_ROOT = ROOT / "backend" / "tracking"


def _load_config() -> dict:
    path = TRACKING_BACKEND_ROOT / "references" / "robot-agent-config.json"
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
        assert "按从上到下连续写可见的稳定细节" in prompt or "否则保留已有 front_view" in prompt
        assert "相似人A：两者都" in prompt
        assert "A 的" in prompt
        assert "目标的" in prompt
        assert "可以通过" in prompt
        assert "后续最容易混淆的人" in prompt
        assert "空字符串" in prompt
        assert "位置、动作、姿态、手势、步态、朝向" in prompt
        assert "不要写“目标区别：……”" in prompt
        assert "不要只写" in prompt
        assert "front、back 或 unknown" in prompt

    assert "初始化 tracking memory" in init_prompt
    assert "已有 tracking memory" in optimize_prompt
    assert "保留已有 front_view" in optimize_prompt
    assert "保留已有 back_view" in optimize_prompt
    assert "版型" in init_prompt
    assert "logo" in init_prompt
    assert "材质感" in init_prompt
    assert "confirmation_reason" in optimize_prompt
    assert "candidate_checks" in optimize_prompt


def test_select_prompts_prefer_stable_appearance_for_hard_cases() -> None:
    config = _load_config()
    init_prompt = str(config["prompts"]["init_skill_prompt"])
    track_prompt = str(config["prompts"]["track_skill_prompt"])

    assert "稳定外观细节" in init_prompt
    assert "不能虚构新框" in init_prompt
    assert "不能依赖单一特征" in init_prompt
    assert "动作、姿态、朝向、位置" in init_prompt
    assert "上衣颜色/深浅/版型" in init_prompt
    assert "鞋" in init_prompt

    assert "身份连续性" in track_prompt
    assert "可迁移" in track_prompt
    assert "unknown" in track_prompt
    assert "参考 crop" in track_prompt
    assert "按从下到上核验" in track_prompt
    assert "不能当正证据，也不能当反证据" in track_prompt
    assert "下半身特征已经足够稳定且没有明显冲突，可以直接 track" in track_prompt
    assert "只有相关部位清楚可见且与历史特征明确矛盾时" in track_prompt
    assert "这里调用 `track` 就说明上一轮目标已经找不到" in track_prompt
    assert "`track` 默认保守" in track_prompt
    assert "candidate_checks" in track_prompt
    assert "周边最像目标的 1 到 3 个人" in track_prompt
    assert "如何和周边最像的人区分开" in track_prompt
    assert "不要只凭远处小框或模糊局部做决定" in track_prompt


def test_memory_optimize_prompt_uses_existing_memory_context() -> None:
    config = _load_config()
    optimize_prompt = str(config["prompts"]["memory_optimize_prompt"])
    memory_contract = str(config["contracts"]["memory_json"])

    assert "{current_memory}" in optimize_prompt
    assert "{confirmation_reason}" in optimize_prompt
    assert "{candidate_checks}" in optimize_prompt
    assert "当前 tracking memory(JSON)" in optimize_prompt
    assert "本轮成功确认理由" in optimize_prompt
    assert "本轮候选核验记录(JSON)" in optimize_prompt
    assert "confirmation_reason" in optimize_prompt
    assert "candidate_checks" in optimize_prompt
    assert "只吸收 confirmation_reason 和 candidate_checks 里真正稳定、可迁移、当前可见的身份正证据" in optimize_prompt
    assert '"core"' in memory_contract
    assert '"front_view"' in memory_contract
    assert '"back_view"' in memory_contract
    assert '"reference_view"' in memory_contract
