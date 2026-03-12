from __future__ import annotations

from tracking_agent.memory_format import (
    DEFAULT_MEMORY_TEXT,
    extract_memory_text,
    normalize_memory_markdown,
    render_memory_markdown,
)


def test_normalize_memory_markdown_wraps_plain_text() -> None:
    normalized = normalize_memory_markdown("目标刚刚从左边转角消失，可能继续向前走。")

    assert normalized.startswith("# Tracking Memory")
    assert "左边转角消失" in extract_memory_text(normalized)


def test_render_and_extract_memory_text_round_trip() -> None:
    original_text = "短发，穿深色上衣，裤子更宽松。和右边更高、穿浅色裤子的人不同。"

    rendered = render_memory_markdown(original_text)
    extracted = extract_memory_text(rendered)

    assert extracted == original_text


def test_normalize_memory_markdown_collapses_model_generated_headings() -> None:
    raw_memory = """
### Target Traits and Distinguishing Description
目标是穿白色上衣、坐在黄色凳子上的人。

### Current Action and Movement Clues
目前坐着看手机，没有明显移动。

### Environment and Distractor Context
右侧有一名黑衣行走者，左侧有人群经过。

### Missing-Target Hypotheses
如果消失，更可能是起身离开座位。

### Next Search Guidance
下一轮先检查原座位附近和左侧通道。
"""

    normalized = normalize_memory_markdown(raw_memory)

    assert "目标是穿白色上衣、坐在黄色凳子上的人。" in extract_memory_text(normalized)
    assert "下一轮先检查原座位附近和左侧通道。" in extract_memory_text(normalized)


def test_normalize_memory_markdown_uses_default_text_for_empty_input() -> None:
    normalized = normalize_memory_markdown("")

    assert extract_memory_text(normalized) == DEFAULT_MEMORY_TEXT
