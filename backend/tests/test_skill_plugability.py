from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.skills import build_viewer_modules, installed_skill_names, project_skill_paths
from skills.web_search.scripts import search_web as web_search_script


ROOT = Path(__file__).resolve().parents[2]


def test_installed_skill_names_include_pluggable_skills() -> None:
    names = set(installed_skill_names())
    assert "tracking" in names
    assert "speech" in names
    assert "web_search" in names


def test_project_skill_paths_can_resolve_new_web_search_skill() -> None:
    paths = project_skill_paths(["web_search"])
    assert [path.name for path in paths] == ["web_search"]


def test_build_viewer_modules_ignores_skills_without_viewer_hooks(tmp_path: Path) -> None:
    modules = build_viewer_modules(
        session={"session_id": "sess_001", "skill_cache": {}, "conversation_history": [], "result_history": []},
        state_root=tmp_path,
        perception_snapshot={"stream_status": {}},
        recent_frames=[],
    )
    assert "speech" not in modules
    assert "web_search" not in modules


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


def test_web_search_script_dry_run_succeeds(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "search_web.py",
            "--query",
            "OpenAI",
            "--dry-run",
        ],
    )

    exit_code = web_search_script.main()

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["query"] == "OpenAI"
    assert payload["results"] == []


def test_web_search_parser_extracts_results_without_backend_changes() -> None:
    payload = web_search_script.search_web(
        query="OpenAI",
        max_results=3,
        fetcher=lambda *_: {
            "Heading": "OpenAI",
            "AbstractText": "AI research and deployment company.",
            "AbstractURL": "https://openai.com/",
            "Results": [],
            "RelatedTopics": [
                {"Text": "ChatGPT", "FirstURL": "https://chatgpt.com/"},
                {"Text": "OpenAI API", "FirstURL": "https://platform.openai.com/"},
            ],
        },
    )

    assert payload["heading"] == "OpenAI"
    assert payload["results"][0]["url"] == "https://openai.com/"
    assert payload["results"][1]["url"] == "https://chatgpt.com/"
