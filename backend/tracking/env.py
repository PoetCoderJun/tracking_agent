from __future__ import annotations

from pathlib import Path
from typing import Mapping

from backend.config import parse_dotenv
from backend.project_paths import resolve_project_path


def load_tracking_env_values(env_file: str | Path) -> dict[str, str]:
    return parse_dotenv(resolve_project_path(env_file))


def float_env_value(values: Mapping[str, str], key: str, default: float) -> float:
    raw = str(values.get(key, "")).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
