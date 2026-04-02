from __future__ import annotations

import importlib
import importlib.util
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


def build_viewer_modules(
    *,
    session: Dict[str, Any],
    state_root: Path,
    perception_snapshot: Dict[str, Any],
    recent_frames: list[Dict[str, Any]],
) -> Dict[str, Any]:
    modules: Dict[str, Any] = {}
    for skill_name in installed_skill_names():
        module_name = f"skills.{skill_name}.viewer"
        if importlib.util.find_spec(module_name) is None:
            continue
        module = importlib.import_module(module_name)
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
