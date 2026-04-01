from __future__ import annotations

from skills.tracking.memory_format import (
    DEFAULT_MEMORY_TEXT,
    normalize_tracking_memory,
    tracking_memory_display_text,
    tracking_memory_prompt_text,
    tracking_memory_summary,
)


def test_normalize_tracking_memory_wraps_legacy_plain_text_into_core() -> None:
    normalized = normalize_tracking_memory("黑色上衣，短发。和右边浅色裤子的人不同。")

    assert normalized["core"] == "黑色上衣，短发。和右边浅色裤子的人不同。"
    assert normalized["front_view"] == ""


def test_normalize_tracking_memory_keeps_existing_fields_when_update_omits_them() -> None:
    previous = {
        "core": "偏瘦男性，黑色短袖上衣、浅卡其短裤、白色运动鞋。",
        "front_view": "短发，脸偏长，黑色短袖上衣。",
        "back_view": "背面黑色短袖上衣，版型宽松。",
        "distinguish": "优先看黑色短袖和浅卡其短裤。",
    }

    normalized = normalize_tracking_memory(
        {
            "core": "",
            "front_view": "短发，脸偏长，黑色短袖上衣，浅卡其短裤，白色运动鞋鞋底偏厚。",
            "back_view": "",
            "distinguish": "优先看浅卡其短裤和厚白鞋底。",
        },
        previous_memory=previous,
    )

    assert normalized["core"] == "偏瘦男性，黑色短袖上衣、浅卡其短裤、白色运动鞋。"
    assert normalized["front_view"] == "短发，脸偏长，黑色短袖上衣，浅卡其短裤，白色运动鞋鞋底偏厚。"
    assert normalized["back_view"] == "背面黑色短袖上衣，版型宽松。"
    assert normalized["distinguish"] == "优先看浅卡其短裤和厚白鞋底。"


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

    assert "摘要：短发、黑色上衣、浅色裤子、白鞋。" in display_text
    assert "核心特征：短发、黑色上衣、浅色裤子、白鞋。" in display_text
    assert "正面特征：正面短发，黑色上衣，浅色裤子，白鞋。" in display_text
    assert "区分点：相似人A为深色长裤；目标区别是浅色裤子和白鞋。" in display_text


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
    previous = {
        "core": "短发、黑色上衣、卡其短裤、白鞋。",
        "front_view": "正面短发，戴眼镜，黑色上衣，卡其短裤，白鞋。",
        "back_view": "背面黑色上衣，版型宽松。",
        "distinguish": "相似人：黑色上衣、深色长裤；目标区别：卡其短裤、白鞋。",
    }

    normalized = normalize_tracking_memory(
        {
            "core": "",
            "front_view": "",
            "back_view": "背面黑色上衣，版型更清楚。",
            "distinguish": "",
        },
        previous_memory=previous,
    )

    assert normalized["distinguish"] == ""
    assert normalized["back_view"] == "背面黑色上衣，版型更清楚。"


def test_normalize_tracking_memory_accepts_legacy_shape() -> None:
    normalized = normalize_tracking_memory(
        {
            "appearance": {
                "head_face": "短发，戴眼镜。",
                "upper_body": "黑色上衣。",
                "lower_body": "卡其短裤。",
                "shoes": "白鞋。",
                "accessories": "",
                "body_shape": "",
            },
            "distinguish": "优先看卡其短裤和白鞋。",
            "summary": "短发、黑色上衣、卡其短裤、白鞋。",
        }
    )

    assert normalized["core"] == "短发、黑色上衣、卡其短裤、白鞋。"
    assert "黑色上衣" in normalized["front_view"]
    assert normalized["distinguish"] == "优先看卡其短裤和白鞋。"


def test_tracking_memory_summary_uses_default_when_empty() -> None:
    assert tracking_memory_summary({"core": "", "front_view": "", "back_view": "", "distinguish": ""}) == DEFAULT_MEMORY_TEXT
