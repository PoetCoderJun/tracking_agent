from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.skills import build_viewer_modules, installed_skill_names, project_skill_paths


ROOT = Path(__file__).resolve().parents[2]


def test_installed_skill_names_include_pluggable_skills() -> None:
    names = set(installed_skill_names())
    assert "tracking" in names
    assert "speech" in names


def test_build_viewer_modules_ignores_skills_without_viewer_hooks(tmp_path: Path) -> None:
    modules = build_viewer_modules(
        session={"session_id": "sess_001", "skill_cache": {}, "conversation_history": [], "result_history": []},
        state_root=tmp_path,
        perception_snapshot={"stream_status": {}},
        recent_frames=[],
    )
    assert "speech" not in modules


def test_speech_cli_dry_run_succeeds(monkeypatch, capsys) -> None:
    from skills.speech.scripts import text_to_speech

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "text_to_speech.py",
            "speak",
            "--input",
            "hello world",
            "--dry-run",
        ],
    )

    exit_code = text_to_speech.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Would write" in captured.out
    assert '"model": "gpt-4o-mini-tts-2025-12-15"' in captured.out
