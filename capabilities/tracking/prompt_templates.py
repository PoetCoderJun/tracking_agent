from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[2]
TRACKING_INIT_SELECT_PROMPT_PATH = (
    ROOT / "skills" / "tracking" / "references" / "prompts" / "tracking-init-select.md"
)
CONTINUOUS_TRACKING_SELECT_PROMPT_PATH = (
    ROOT / "capabilities" / "tracking" / "references" / "prompts" / "continuous-tracking-select.md"
)
TRACKING_MEMORY_INIT_PROMPT_PATH = (
    ROOT / "capabilities" / "tracking" / "references" / "prompts" / "tracking-memory-init.md"
)
TRACKING_MEMORY_UPDATE_PROMPT_PATH = (
    ROOT / "capabilities" / "tracking" / "references" / "prompts" / "tracking-memory-update.md"
)
TRACKING_RUNTIME_CONFIG_PATH = (
    ROOT / "capabilities" / "tracking" / "references" / "tracking-runtime-config.json"
)

PROMPT_TEMPLATE_PATHS = {
    "tracking_init_select_prompt": TRACKING_INIT_SELECT_PROMPT_PATH,
    "continuous_tracking_select_prompt": CONTINUOUS_TRACKING_SELECT_PROMPT_PATH,
    "tracking_memory_init_prompt": TRACKING_MEMORY_INIT_PROMPT_PATH,
    "tracking_memory_update_prompt": TRACKING_MEMORY_UPDATE_PROMPT_PATH,
}


def load_tracking_runtime_config(config_path: Path = TRACKING_RUNTIME_CONFIG_PATH) -> Dict[str, Any]:
    return json.loads(config_path.read_text(encoding="utf-8"))


def prompt_template_path(
    *,
    prompt_key: str,
) -> Path:
    resolved_path = PROMPT_TEMPLATE_PATHS.get(prompt_key)
    if resolved_path is None:
        raise KeyError(f"Missing prompt template path for {prompt_key!r}")
    resolved_path = resolved_path.resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Missing prompt template file for {prompt_key!r}: {resolved_path}")
    return resolved_path


def load_prompt_template(
    *,
    prompt_key: str,
) -> str:
    return prompt_template_path(prompt_key=prompt_key).read_text(encoding="utf-8").strip()


def render_prompt_template(
    *,
    prompt_key: str,
    **template_values: Any,
) -> str:
    return load_prompt_template(prompt_key=prompt_key).format(**template_values)
