from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB_SEARCH_SKILL = ROOT / "skills" / "web-search" / "SKILL.md"
FEISHU_SKILL = ROOT / "skills" / "feishu" / "SKILL.md"
TTS_SKILL = ROOT / "skills" / "tts" / "SKILL.md"


def test_web_search_skill_mentions_deterministic_helper() -> None:
    skill = WEB_SEARCH_SKILL.read_text(encoding="utf-8")

    assert "python ./skills/web-search/scripts/search_turn.py" in skill
    assert "ROBOT_AGENT_STATE_ROOT" in skill
    assert "answer the user naturally" in skill
    assert "Do not inspect files, do not verify artifacts" in skill


def test_feishu_skill_mentions_mock_notification_helper() -> None:
    skill = FEISHU_SKILL.read_text(encoding="utf-8")

    assert "python -m skills.feishu.scripts.notify_turn" in skill
    assert "ROBOT_AGENT_STATE_ROOT" in skill
    assert "mock Feishu outbox" in skill
    assert "reply naturally to the user" in skill


def test_tts_skill_mentions_deterministic_helper() -> None:
    skill = TTS_SKILL.read_text(encoding="utf-8")

    assert "python -m skills.tts.scripts.speak_turn" in skill
    assert "ROBOT_AGENT_STATE_ROOT" in skill
    assert "reply naturally to the user" in skill
    assert "mock tts outbox" in skill
