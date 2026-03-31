from __future__ import annotations

from skills.tracking.memory_format import (
    DEFAULT_MEMORY_TEXT,
    normalize_tracking_memory,
    tracking_memory_display_text,
    tracking_memory_prompt_text,
    tracking_memory_summary,
)


def test_normalize_tracking_memory_wraps_legacy_plain_text_into_summary() -> None:
    normalized = normalize_tracking_memory("黑色上衣，短发。和右边浅色裤子的人不同。")

    assert normalized["summary"] == "黑色上衣，短发。和右边浅色裤子的人不同。"
    assert normalized["appearance"]["upper_body"] == ""


def test_normalize_tracking_memory_keeps_existing_fields_when_update_omits_them() -> None:
    previous = {
        "appearance": {
            "head_face": "短发，脸偏长。",
            "upper_body": "黑色短袖上衣。",
            "lower_body": "浅卡其短裤。",
            "shoes": "白色运动鞋。",
            "accessories": "",
            "body_shape": "偏瘦偏高。",
        },
        "distinguish": "优先看黑色短袖和浅卡其短裤。",
        "summary": "黑色短袖、浅卡其短裤、白鞋。",
    }

    normalized = normalize_tracking_memory(
        {
            "appearance": {
                "head_face": "",
                "upper_body": "",
                "lower_body": "浅卡其短裤，裤长到膝上。",
                "shoes": "白色运动鞋，鞋底偏厚。",
                "accessories": "",
                "body_shape": "",
            },
            "distinguish": "优先看浅卡其短裤和厚白鞋底。",
            "summary": "黑色短袖、浅卡其短裤、厚白鞋底。",
        },
        previous_memory=previous,
    )

    assert normalized["appearance"]["head_face"] == "短发，脸偏长。"
    assert normalized["appearance"]["upper_body"] == "黑色短袖上衣。"
    assert normalized["appearance"]["lower_body"] == "浅卡其短裤，裤长到膝上。"
    assert normalized["appearance"]["shoes"] == "白色运动鞋，鞋底偏厚。"
    assert normalized["distinguish"] == "优先看浅卡其短裤和厚白鞋底。"


def test_tracking_memory_prompt_text_serializes_structured_json() -> None:
    prompt_text = tracking_memory_prompt_text(
        {
            "appearance": {
                "head_face": "短发。",
                "upper_body": "黑色上衣。",
                "lower_body": "",
                "shoes": "",
                "accessories": "",
                "body_shape": "",
            },
            "distinguish": "",
            "summary": "短发、黑色上衣。",
        }
    )

    assert '"appearance"' in prompt_text
    assert '"head_face"' in prompt_text
    assert "短发、黑色上衣。" in prompt_text


def test_tracking_memory_display_text_renders_sections() -> None:
    display_text = tracking_memory_display_text(
        {
            "appearance": {
                "head_face": "短发。",
                "upper_body": "黑色上衣。",
                "lower_body": "浅色裤子。",
                "shoes": "白鞋。",
                "accessories": "",
                "body_shape": "偏瘦。",
            },
            "distinguish": "和旁边深色长裤的人区分时优先看浅色裤子。",
            "summary": "短发、黑色上衣、浅色裤子、白鞋。",
        }
    )

    assert "摘要：短发、黑色上衣、浅色裤子、白鞋。" in display_text
    assert "上装：黑色上衣。" in display_text
    assert "鞋子：白鞋。" in display_text
    assert "区分点：和旁边深色长裤的人区分时优先看浅色裤子。" in display_text


def test_normalize_tracking_memory_clears_distinguish_when_no_confusing_person() -> None:
    normalized = normalize_tracking_memory(
        {
            "appearance": {
                "head_face": "短发。",
                "upper_body": "黑色上衣。",
                "lower_body": "卡其短裤。",
                "shoes": "白鞋。",
                "accessories": "",
                "body_shape": "",
            },
            "distinguish": "无其他行人",
            "summary": "短发、黑色上衣、卡其短裤、白鞋。",
        }
    )

    assert normalized["distinguish"] == ""


def test_normalize_tracking_memory_keeps_distinguish_when_it_contains_real_comparison() -> None:
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
            "distinguish": "相似人：黑色上衣、深色长裤、无眼镜；目标区别：卡其短裤、白鞋、戴眼镜。",
            "summary": "短发、黑色上衣、卡其短裤、白鞋。",
        }
    )

    assert normalized["distinguish"] == "相似人：黑色上衣、深色长裤、无眼镜；目标区别：卡其短裤、白鞋、戴眼镜。"


def test_normalize_tracking_memory_allows_structured_update_to_clear_previous_distinguish() -> None:
    previous = {
        "appearance": {
            "head_face": "短发，戴眼镜。",
            "upper_body": "黑色上衣。",
            "lower_body": "卡其短裤。",
            "shoes": "白鞋。",
            "accessories": "",
            "body_shape": "",
        },
        "distinguish": "相似人：黑色上衣、深色长裤；目标区别：卡其短裤、白鞋。",
        "summary": "短发、黑色上衣、卡其短裤、白鞋。",
    }

    normalized = normalize_tracking_memory(
        {
            "appearance": {
                "head_face": "",
                "upper_body": "黑色上衣，背面版型宽松。",
                "lower_body": "",
                "shoes": "",
                "accessories": "",
                "body_shape": "",
            },
            "distinguish": "",
            "summary": "黑色上衣、卡其短裤、白鞋。",
        },
        previous_memory=previous,
    )

    assert normalized["distinguish"] == ""
    assert normalized["appearance"]["upper_body"] == "黑色上衣，背面版型宽松。"


def test_tracking_memory_summary_uses_default_when_empty() -> None:
    assert tracking_memory_summary({"appearance": {}, "distinguish": "", "summary": ""}) == DEFAULT_MEMORY_TEXT
