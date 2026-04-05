from __future__ import annotations

import pytest

from backend.tracking.memory import (
    DEFAULT_MEMORY_TEXT,
    normalize_tracking_memory,
    tracking_memory_flash_prompt_text,
    tracking_memory_display_text,
    tracking_memory_prompt_text,
    tracking_memory_summary,
)


def test_normalize_tracking_memory_requires_canonical_json_object() -> None:
    with pytest.raises(ValueError):
        normalize_tracking_memory("黑色上衣，短发。和右边浅色裤子的人不同。")

    with pytest.raises(ValueError):
        normalize_tracking_memory({"core": "only core"})


def test_tracking_memory_prompt_text_serializes_new_json_shape() -> None:
    prompt_text = tracking_memory_prompt_text(
        {
            "core": "短发、黑色上衣。",
            "front_view": "正面是短发，黑色上衣。",
            "back_view": "",
            "distinguish": "",
        }
    )

    assert '"core"' in prompt_text
    assert '"front_view"' in prompt_text
    assert "短发、黑色上衣。" in prompt_text


def test_tracking_memory_display_text_renders_sections() -> None:
    display_text = tracking_memory_display_text(
        {
            "core": "短发、黑色上衣、浅色裤子、白鞋。",
            "front_view": "正面短发，黑色上衣，浅色裤子，白鞋。",
            "back_view": "背面黑色上衣，裤子偏直筒。",
            "distinguish": "相似人A为深色长裤；目标区别是浅色裤子和白鞋。",
        }
    )

    assert "核心特征：短发、黑色上衣、浅色裤子、白鞋。" in display_text
    assert "正面特征：正面短发，黑色上衣，浅色裤子，白鞋。" in display_text
    assert "区分点：相似人A为深色长裤；目标区别是浅色裤子和白鞋。" in display_text
    assert "摘要：" not in display_text


def test_tracking_memory_flash_prompt_text_omits_summary_line() -> None:
    prompt_text = tracking_memory_flash_prompt_text(
        {
            "core": "短发、黑色上衣、浅色裤子、白鞋。",
            "front_view": "正面短发，黑色上衣，浅色裤子，白鞋。",
            "back_view": "",
            "distinguish": "优先看浅色裤子和白鞋。",
        }
    )

    assert "- core: 短发、黑色上衣、浅色裤子、白鞋。" in prompt_text
    assert "- summary:" not in prompt_text


def test_normalize_tracking_memory_clears_distinguish_when_no_confusing_person() -> None:
    normalized = normalize_tracking_memory(
        {
            "core": "短发、黑色上衣、卡其短裤、白鞋。",
            "front_view": "正面短发，黑色上衣，卡其短裤，白鞋。",
            "back_view": "",
            "distinguish": "无其他行人",
        }
    )

    assert normalized["distinguish"] == ""


def test_normalize_tracking_memory_keeps_distinguish_when_it_contains_real_comparison() -> None:
    normalized = normalize_tracking_memory(
        {
            "core": "短发、黑色上衣、卡其短裤、白鞋。",
            "front_view": "正面短发，戴眼镜，黑色上衣，卡其短裤，白鞋。",
            "back_view": "",
            "distinguish": "相似人：黑色上衣、深色长裤、无眼镜；目标区别：卡其短裤、白鞋、戴眼镜。",
        }
    )

    assert normalized["distinguish"] == "相似人：黑色上衣、深色长裤、无眼镜；目标区别：卡其短裤、白鞋、戴眼镜。"


def test_normalize_tracking_memory_allows_update_to_clear_previous_distinguish() -> None:
    normalized = normalize_tracking_memory(
        {
            "core": "短发、黑色上衣、卡其短裤、白鞋。",
            "front_view": "正面短发，戴眼镜，黑色上衣，卡其短裤，白鞋。",
            "back_view": "背面黑色上衣，版型更清楚。",
            "distinguish": "",
        }
    )

    assert normalized["distinguish"] == ""
    assert normalized["back_view"] == "背面黑色上衣，版型更清楚。"


def test_tracking_memory_summary_uses_default_when_empty() -> None:
    assert tracking_memory_summary({"core": "", "front_view": "", "back_view": "", "distinguish": ""}) == DEFAULT_MEMORY_TEXT
