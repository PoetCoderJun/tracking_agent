from __future__ import annotations

from skills.catalog import skill_script_path
from interfaces.viewer import skill_modules


def test_skill_script_path_resolves_skill_local_viewer_module() -> None:
    viewer_module = skill_script_path("tracking-init", "viewer_module.py")

    assert viewer_module is not None
    assert viewer_module.name == "viewer_module.py"
    assert viewer_module.parent.name == "scripts"
    assert viewer_module.parent.parent.name == "tracking-init"


def test_viewer_skill_modules_load_from_skill_package_not_interface() -> None:
    module = skill_modules._load_skill_viewer_module("tracking-init")

    assert module is not None
    assert callable(getattr(module, "build_viewer_module", None))
