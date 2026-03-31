#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import parse_dotenv
from backend.perception.service import LocalPerceptionService
from backend.persistence import resolve_session_id
from backend.project_paths import resolve_project_path


def _float_env_value(values: Dict[str, str], key: str, default: float) -> float:
    raw = str(values.get(key, "")).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def parse_args() -> argparse.Namespace:
    bootstrap_parser = argparse.ArgumentParser(add_help=False)
    bootstrap_parser.add_argument("--env-file", default=".ENV")
    bootstrap_args, _ = bootstrap_parser.parse_known_args()
    env_values = parse_dotenv(resolve_project_path(bootstrap_args.env_file))

    parser = argparse.ArgumentParser(
        description="Run the tracking agent loop and print appended agent chat logs."
    )
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--device-id", default="robot_01")
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--env-file", default=bootstrap_args.env_file)
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    parser.add_argument("--pi-binary", default="pi")
    parser.add_argument("--continue-text", default="继续跟踪")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=_float_env_value(env_values, "QUERY_INTERVAL_SECONDS", 3.0),
    )
    parser.add_argument(
        "--recovery-interval-seconds",
        type=float,
        default=_float_env_value(env_values, "TRACKING_RECOVERY_INTERVAL_SECONDS", 1.0),
    )
    parser.add_argument(
        "--idle-sleep-seconds",
        type=float,
        default=_float_env_value(env_values, "TRACKING_IDLE_SLEEP_SECONDS", 3.0),
    )
    parser.add_argument(
        "--presence-check-seconds",
        type=float,
        default=_float_env_value(env_values, "TRACKING_PRESENCE_CHECK_SECONDS", 1.0),
    )
    parser.add_argument("--viewer-host", default="127.0.0.1")
    parser.add_argument("--viewer-port", type=int, default=8765)
    parser.add_argument("--viewer-poll-interval", type=float, default=1.0)
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--stop-file", default=None)
    parser.add_argument("--chat-poll-interval", type=float, default=0.5)
    parser.add_argument("--init-text", default="")
    parser.add_argument("--startup-timeout-seconds", type=float, default=60.0)
    return parser.parse_args()


def _loop_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "scripts.run_tracking_loop",
        "--device-id",
        str(args.device_id),
        "--state-root",
        str(args.state_root),
        "--env-file",
        str(args.env_file),
        "--artifacts-root",
        str(args.artifacts_root),
        "--pi-binary",
        str(args.pi_binary),
        "--continue-text",
        str(args.continue_text),
        "--interval-seconds",
        str(args.interval_seconds),
        "--recovery-interval-seconds",
        str(args.recovery_interval_seconds),
        "--idle-sleep-seconds",
        str(args.idle_sleep_seconds),
        "--presence-check-seconds",
        str(args.presence_check_seconds),
        "--viewer-host",
        str(args.viewer_host),
        "--viewer-port",
        str(args.viewer_port),
        "--viewer-poll-interval",
        str(args.viewer_poll_interval),
        "--no-viewer-stream",
    ]
    if args.session_id not in (None, ""):
        command.extend(["--session-id", str(args.session_id)])
    if args.max_turns is not None:
        command.extend(["--max-turns", str(args.max_turns)])
    if args.stop_file not in (None, ""):
        command.extend(["--stop-file", str(args.stop_file)])
    return command


def _session_file(state_root: Path, session_id: str) -> Path:
    return state_root / "sessions" / session_id / "session.json"


def _entry_key(entry: Dict[str, object]) -> Tuple[str, str, str]:
    return (
        str(entry.get("role", "")).strip(),
        str(entry.get("timestamp", "")).strip(),
        str(entry.get("text", "")).strip(),
    )


def _tail_chat_logs(args: argparse.Namespace, stop_event: threading.Event) -> None:
    state_root = resolve_project_path(args.state_root)
    seen: Dict[str, Set[Tuple[str, str, str]]] = {}
    while not stop_event.is_set():
        session_id = resolve_session_id(state_root=state_root, session_id=args.session_id)
        if session_id is not None:
            session_file = _session_file(state_root, session_id)
            if session_file.exists():
                try:
                    payload = json.loads(session_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    time.sleep(args.chat_poll_interval)
                    continue
                entries = list(payload.get("conversation_history") or [])
                known = seen.setdefault(session_id, set())
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    key = _entry_key(entry)
                    if key in known:
                        continue
                    known.add(key)
                    print(
                        json.dumps(
                            {
                                "session_id": session_id,
                                "status": "agent_chat",
                                "role": key[0],
                                "timestamp": key[1],
                                "text": key[2],
                            },
                            ensure_ascii=True,
                        ),
                        flush=True,
                    )
        stop_event.wait(args.chat_poll_interval)


def _session_has_frame(state_root: Path, session_id: str, *, device_id: str) -> bool:
    _ = device_id
    return LocalPerceptionService(state_root=state_root).latest_camera_observation(session_id=session_id) is not None


def _run_init_chat(args: argparse.Namespace) -> int:
    init_text = str(args.init_text or "").strip()
    if not init_text:
        return 0

    state_root = resolve_project_path(args.state_root)
    started = time.monotonic()
    session_id: Optional[str] = args.session_id
    while True:
        session_id = resolve_session_id(state_root=state_root, session_id=session_id)
        if session_id is not None and _session_has_frame(state_root, session_id, device_id=str(args.device_id)):
            break
        if time.monotonic() - started > float(args.startup_timeout_seconds):
            raise TimeoutError("Timed out waiting for the first perception frame before init chat.")
        time.sleep(0.5)

    command = [
        sys.executable,
        "-m",
        "backend.cli",
        "chat",
        "--session-id",
        str(session_id),
        "--text",
        init_text,
        "--device-id",
        str(args.device_id),
        "--state-root",
        str(args.state_root),
        "--artifacts-root",
        str(args.artifacts_root),
        "--env-file",
        str(args.env_file),
        "--pi-binary",
        str(args.pi_binary),
        "--skill",
        "tracking",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.stdout.strip():
        print(completed.stdout.strip(), flush=True)
    if completed.stderr.strip():
        print(completed.stderr.strip(), file=sys.stderr, flush=True)
    return int(completed.returncode)


def main() -> int:
    args = parse_args()
    stop_event = threading.Event()
    tail_thread = threading.Thread(
        target=_tail_chat_logs,
        args=(args, stop_event),
        name="tracking-agent-chat-tail",
        daemon=True,
    )
    tail_thread.start()

    init_status = _run_init_chat(args)
    if init_status != 0:
        stop_event.set()
        tail_thread.join(timeout=1)
        return init_status

    process = subprocess.Popen(_loop_command(args))
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            return process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait()
    finally:
        stop_event.set()
        tail_thread.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
