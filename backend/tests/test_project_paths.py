from __future__ import annotations

from pathlib import Path

from backend.project_paths import PROJECT_ROOT, resolve_project_path


def test_resolve_project_path_keeps_absolute_paths() -> None:
    absolute = Path("/tmp/example.txt")
    assert resolve_project_path(absolute) == absolute


def test_resolve_project_path_resolves_repo_relative_paths() -> None:
    resolved = resolve_project_path("backend/tests/fixtures/demo_video.mp4")
    assert resolved == PROJECT_ROOT / "backend/tests/fixtures/demo_video.mp4"
