from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Dict

from skills.catalog import installed_skill_names, skill_script_path

def _load_module_from_path(*, path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def _load_skill_viewer_module(skill_name: str):
    viewer_module_path = skill_script_path(skill_name, "viewer_module.py")
    if viewer_module_path is None:
        return None
    return _load_module_from_path(
        path=viewer_module_path,
        module_name=f"{skill_name.replace('-', '_')}_viewer_module",
    )


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
