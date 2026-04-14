from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    main_model: str
    sub_model: str
    timeout_seconds: int
    sample_fps: float
    recent_frame_count: int
    chat_model: str = "qwen3.5-flash"


def parse_dotenv(env_path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_settings(env_path: Optional[Path] = None) -> Settings:
    path = env_path or Path(".ENV")
    values = parse_dotenv(path)
    default_model = values.get("DASHSCOPE_MODEL", "qwen3.5-plus")

    return Settings(
        api_key=values.get("DASHSCOPE_API_KEY", ""),
        base_url=values.get(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        model=default_model,
        main_model=values.get("DASHSCOPE_MAIN_MODEL", default_model),
        sub_model=values.get("DASHSCOPE_SUB_MODEL", "qwen3.5-flash"),
        chat_model=values.get("DASHSCOPE_CHAT_MODEL", "qwen3.5-flash"),
        timeout_seconds=int(values.get("DASHSCOPE_TIMEOUT_SECONDS", "120")),
        sample_fps=float(values.get("FRAME_SAMPLE_FPS", "1")),
        recent_frame_count=int(values.get("RECENT_FRAME_COUNT", "3")),
    )
