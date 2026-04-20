from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".ENV"
DEFAULT_TRACKING_STT_WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
TRACKING_VAD_MODEL_ENV = "TRACKING_VAD_MODEL_PATH"
LEGACY_POINTING_VAD_MODEL_ENV = "POINTING_VAD_MODEL_PATH"


def _parse_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _env_values() -> Dict[str, str]:
    values = _parse_dotenv(ENV_PATH)
    merged = dict(values)
    merged.update({key: value for key, value in os.environ.items() if isinstance(value, str)})
    return merged


def env_value(name: str, *, default: str = "") -> str:
    values = _env_values()
    return str(values.get(name, default)).strip()


def require_env(name: str, *legacy_names: str) -> str:
    value = env_value(name, default="")
    if value:
        return value
    for legacy_name in legacy_names:
        legacy_value = env_value(legacy_name, default="")
        if legacy_value:
            return legacy_value
    legacy_hint = ""
    if legacy_names:
        legacy_hint = f" Legacy names also checked: {', '.join(legacy_names)}."
    raise RuntimeError(
        f"Required environment variable {name} is not set.{legacy_hint} "
        "Configure it in .ENV before using the local STT pipeline."
    )


def asr_settings() -> Dict[str, str]:
    return {
        "ws_url": require_env("TRACKING_STT_WS_URL", "POINTING_STT_WS_URL")
        or DEFAULT_TRACKING_STT_WS_URL,
        "app_key": require_env("TRACKING_STT_APP_KEY", "POINTING_STT_APP_KEY"),
        "access_key": require_env("TRACKING_STT_ACCESS_KEY", "POINTING_STT_ACCESS_KEY"),
    }


def vad_model_path(default_path: Path) -> Path:
    configured = (
        env_value(TRACKING_VAD_MODEL_ENV, default="")
        or env_value(LEGACY_POINTING_VAD_MODEL_ENV, default="")
        or str(default_path)
    )
    return Path(configured).expanduser().resolve()
