from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEECH_SKILL = ROOT / "skills" / "speech" / "SKILL.md"


def test_speech_skill_mentions_robot_agent_result_contract() -> None:
    skill = SPEECH_SKILL.read_text(encoding="utf-8")

    assert '"status": "idle" | "processed"' in skill
    assert '"skill_name": "speech" | null' in skill
    assert '"session_result": object | null' in skill


def test_speech_skill_uses_bundled_tts_script() -> None:
    skill = SPEECH_SKILL.read_text(encoding="utf-8")

    assert "scripts/text_to_speech.py" in skill
