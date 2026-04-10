from __future__ import annotations

from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def installed_skill_names() -> list[str]:
    skills_root = ROOT / "skills"
    if not skills_root.exists():
        return []

    names: list[str] = []
    for candidate in sorted(skills_root.iterdir()):
        if not candidate.is_dir():
            continue
        if not (candidate / "SKILL.md").exists():
            continue
        names.append(candidate.name)
    return names


def skill_path(skill_name: str) -> Path:
    candidate = ROOT / "skills" / str(skill_name).strip()
    if not candidate.exists() or not (candidate / "SKILL.md").exists():
        available = ", ".join(installed_skill_names()) or "(none)"
        raise ValueError(f"Unknown skill {skill_name!r}. Available skills: {available}")
    return candidate


def skill_script_path(skill_name: str, relative_path: str) -> Path | None:
    candidate = skill_path(skill_name) / "scripts" / str(relative_path).strip()
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def _skill_paths() -> dict[str, Path]:
    return {name: skill_path(name) for name in installed_skill_names()}


def project_skill_paths(enabled_skills: Any = None) -> list[Path]:
    skill_map = _skill_paths()
    if enabled_skills in (None, ""):
        return list(skill_map.values())

    requested: list[str] = []
    seen: set[str] = set()
    for item in (enabled_skills if isinstance(enabled_skills, list) else [enabled_skills]):
        for chunk in str(item).split(","):
            name = chunk.strip()
            if not name or name in seen:
                continue
            requested.append(name)
            seen.add(name)

    missing = [name for name in requested if name not in skill_map]
    if missing:
        available = ", ".join(skill_map.keys()) or "(none)"
        raise ValueError(f"Unknown skills requested: {', '.join(missing)}. Available skills: {available}")
    return [skill_map[name] for name in requested]
