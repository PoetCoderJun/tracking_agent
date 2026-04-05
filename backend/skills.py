from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Dict


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


def _skill_paths() -> dict[str, Path]:
    return {name: ROOT / "skills" / name for name in installed_skill_names()}


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
        raise ValueError(
            f"Unknown skills requested: {', '.join(missing)}. Available skills: {available}"
        )
    return [skill_map[name] for name in requested]


def _load_skill_viewer_module(skill_name: str):
    skill_viewer_module_path = ROOT / "skills" / skill_name / "viewer.py"
    if skill_viewer_module_path.exists():
        return importlib.import_module(f"skills.{skill_name}.viewer")

    backend_viewer_module_path = ROOT / "backend" / skill_name / "viewer.py"
    if backend_viewer_module_path.exists():
        return importlib.import_module(f"backend.{skill_name}.viewer")
    return None


def build_viewer_modules(
    *,
    session: Dict[str, Any],
    state_root: Path,
    perception_snapshot: Dict[str, Any],
    recent_frames: list[Dict[str, Any]],
) -> Dict[str, Any]:
    modules: Dict[str, Any] = {}
    for skill_name in installed_skill_names():
        module = _load_skill_viewer_module(skill_name)
        if module is None:
            continue
        builder = getattr(module, "build_viewer_module", None)
        if not callable(builder):
            continue
        payload = builder(
            session=session,
            state_root=state_root,
            perception_snapshot=perception_snapshot,
            recent_frames=recent_frames,
        )
        if payload is None:
            continue
        modules[skill_name] = payload
    return modules
