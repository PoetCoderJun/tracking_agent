from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping

from backend.config import parse_dotenv
from backend.perception.service import LocalPerceptionService
from backend.persistence import resolve_session_id
from backend.project_paths import resolve_project_path

TRACKING_SKILL_NAME = "tracking"
DEFAULT_STARTUP_POLL_INTERVAL_SECONDS = 0.5


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


def build_tracking_chat_command(
    *,
    session_id: str,
    text: str,
    device_id: str,
    state_root: str | Path,
    artifacts_root: str | Path,
    env_file: str | Path,
    pi_binary: str = "pi",
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "backend.cli",
        "chat",
        "--session-id",
        str(session_id),
        "--text",
        str(text),
        "--device-id",
        str(device_id),
        "--state-root",
        str(state_root),
        "--artifacts-root",
        str(artifacts_root),
        "--env-file",
        str(env_file),
        "--pi-binary",
        str(pi_binary),
        "--skill",
        TRACKING_SKILL_NAME,
    ]


def _session_has_frame(state_root: Path, session_id: str) -> bool:
    return LocalPerceptionService(state_root=state_root).latest_camera_observation(
        session_id=session_id
    ) is not None


def wait_for_first_tracking_frame(
    *,
    state_root: Path,
    requested_session_id: str | None,
    timeout_seconds: float,
    poll_interval_seconds: float = DEFAULT_STARTUP_POLL_INTERVAL_SECONDS,
) -> str:
    started = time.monotonic()
    session_id = requested_session_id
    while True:
        session_id = resolve_session_id(state_root=state_root, session_id=session_id)
        if session_id is not None and _session_has_frame(state_root, session_id):
            return session_id
        if time.monotonic() - started > float(timeout_seconds):
            raise TimeoutError(
                "Timed out waiting for the first perception frame before init chat."
            )
        time.sleep(poll_interval_seconds)


def run_tracking_chat_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)
