from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB_SEARCH_SKILL = ROOT / "skills" / "web_search" / "SKILL.md"
FEISHU_SKILL = ROOT / "skills" / "feishu" / "SKILL.md"


def test_web_search_skill_mentions_deterministic_helper() -> None:
    skill = WEB_SEARCH_SKILL.read_text(encoding="utf-8")

    assert "python -m skills.web_search.scripts.search_turn" in skill
    assert "answer the user naturally" in skill
    assert "Do not inspect files, do not verify artifacts" in skill


def test_feishu_skill_mentions_mock_notification_helper() -> None:
    skill = FEISHU_SKILL.read_text(encoding="utf-8")

    assert "python -m skills.feishu.scripts.notify_turn" in skill
    assert "mock Feishu outbox" in skill
    assert "reply naturally to the user" in skill
