from __future__ import annotations

from typing import List


MEMORY_TITLE = "Tracking Memory"
DEFAULT_MEMORY_TEXT = "等待根据最新确认画面继续补充目标特征，并说明和周围人的区分点。"


def render_memory_markdown(memory_text: str) -> str:
    content = memory_text.strip() or DEFAULT_MEMORY_TEXT
    return f"# {MEMORY_TITLE}\n\n{content}\n"


def extract_memory_text(memory_markdown: str) -> str:
    content_lines: List[str] = []
    for line in memory_markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        content_lines.append(stripped)

    content = " ".join(content_lines).strip()
    if not content:
        content = memory_markdown.strip() or DEFAULT_MEMORY_TEXT
    return content


def normalize_memory_markdown(memory_markdown: str) -> str:
    stripped = memory_markdown.strip()
    if not stripped:
        return render_memory_markdown(DEFAULT_MEMORY_TEXT)

    return render_memory_markdown(extract_memory_text(stripped))
