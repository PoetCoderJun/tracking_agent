#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMERA_SOURCE = "camera"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Start the tracking stack with one command: camera perception plus an optional "
            "tracking runtime loop that also serves the viewer websocket stream."
        )
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_CAMERA_SOURCE,
        help="Video file path or camera index such as 0. Defaults to the local computer camera.",
    )
    parser.add_argument("--output-dir", default="./.runtime/tracking-perception")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--device-id", default="robot_01")
    parser.add_argument("--observation-text", default="")
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--device", default=None)
    parser.add_argument("--tracker", default=None)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=None)
    parser.add_argument("--vid-stride", type=int, default=1)
    parser.add_argument("--sample-every", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=3.0)
    parser.add_argument("--realtime-playback", action="store_true")
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--max-event-log-lines", type=int, default=300)
    parser.add_argument("--person-class-id", type=int, default=0)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    parser.add_argument("--pi-binary", default="pi")
    parser.add_argument("--continue-text", default="继续跟踪")
    parser.add_argument("--idle-sleep-seconds", type=float, default=1.0)
    parser.add_argument(
        "--init-text",
        default=None,
        help="Optional initial tracking instruction to send once the first perception frame is ready.",
    )
    parser.add_argument(
        "--startup-timeout-seconds",
        type=float,
        default=60.0,
        help="How long to wait for the new session and its first frame before treating startup as failed.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument(
        "--no-auto-loop",
        action="store_true",
        help="Start only perception, without the tracking runtime loop or its coupled viewer stream.",
    )
    parser.add_argument(
        "--no-viewer-stream",
        action="store_true",
        help="Disable the websocket stream coupled to the tracking runtime loop.",
    )
    return parser.parse_args()


def _append_optional(command: List[str], flag: str, value: object) -> None:
    if value in (None, ""):
        return
    command.extend([flag, str(value)])


def _perception_command(args: argparse.Namespace) -> List[str]:
    command = [
        sys.executable,
        "-m",
        "scripts.run_tracking_perception",
        "--source",
        str(args.source),
        "--output-dir",
        str(args.output_dir),
        "--device-id",
        str(args.device_id),
        "--observation-text",
        str(args.observation_text),
        "--state-root",
        str(args.state_root),
        "--model",
        str(args.model),
        "--conf",
        str(args.conf),
        "--vid-stride",
        str(args.vid_stride),
        "--sample-every",
        str(args.sample_every),
        "--interval-seconds",
        str(args.interval_seconds),
        "--max-event-log-lines",
        str(args.max_event_log_lines),
        "--person-class-id",
        str(args.person_class_id),
    ]
    _append_optional(command, "--session-id", args.session_id)
    _append_optional(command, "--device", args.device)
    _append_optional(command, "--tracker", args.tracker)
    _append_optional(command, "--imgsz", args.imgsz)
    _append_optional(command, "--max-events", args.max_events)
    if args.realtime_playback:
        command.append("--realtime-playback")
    return command


def _loop_command(args: argparse.Namespace) -> List[str]:
    return _loop_command_for_session(args, session_id=args.session_id)


def _loop_command_for_session(args: argparse.Namespace, *, session_id: str | None) -> List[str]:
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
        "--idle-sleep-seconds",
        str(args.idle_sleep_seconds),
        "--viewer-host",
        str(args.host),
        "--viewer-port",
        str(args.port),
        "--viewer-poll-interval",
        str(args.poll_interval),
    ]
    _append_optional(command, "--session-id", session_id)
    if args.no_viewer_stream:
        command.append("--no-viewer-stream")
    return command


def _chat_command(args: argparse.Namespace, *, session_id: str, text: str) -> List[str]:
    command = [
        sys.executable,
        "-m",
        "backend.cli",
        "chat",
        "--session-id",
        str(session_id),
        "--text",
        str(text),
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
    return command


def _viewer_command(args: argparse.Namespace) -> List[str]:
    command = [
        sys.executable,
        "-m",
        "scripts.run_tracking_viewer_stream",
        "--state-root",
        str(args.state_root),
        "--host",
        str(args.host),
        "--port",
        str(args.port),
        "--poll-interval",
        str(args.poll_interval),
    ]
    _append_optional(command, "--session-id", args.session_id)
    return command


def _terminate_processes(processes: List[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is not None:
            continue
        process.terminate()
    deadline = time.time() + 5
    for process in processes:
        if process.poll() is not None:
            continue
        remaining = max(0.0, deadline - time.time())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()


def _active_session_id(state_root: Path) -> Optional[str]:
    active_path = state_root / "active_session.json"
    if not active_path.exists():
        return None
    payload = json.loads(active_path.read_text(encoding="utf-8"))
    session_id = str(payload.get("session_id", "")).strip()
    return session_id or None


def _session_frame_count(state_root: Path, session_id: str) -> int:
    session_path = state_root / "sessions" / session_id / "session.json"
    if not session_path.exists():
        return 0
    payload = json.loads(session_path.read_text(encoding="utf-8"))
    return len(payload.get("recent_frames") or [])


def _wait_for_started_session(
    *,
    args: argparse.Namespace,
    perception_process: subprocess.Popen,
    previous_active_session_id: str | None,
) -> str:
    state_root = (ROOT / args.state_root).resolve()
    deadline = time.time() + args.startup_timeout_seconds
    while time.time() < deadline:
        return_code = perception_process.poll()
        if return_code is not None:
            raise RuntimeError(
                f"perception exited with code {return_code} before the stack saw any frame in the new session."
            )

        session_id = str(args.session_id or "").strip()
        if not session_id:
            active_session_id = _active_session_id(state_root)
            if active_session_id in (None, "", previous_active_session_id):
                time.sleep(0.5)
                continue
            session_id = active_session_id

        if _session_frame_count(state_root, session_id) > 0:
            return session_id
        time.sleep(0.5)

    raise TimeoutError(
        "Timed out waiting for the first perception frame in the new session. "
        "Perception did not ingest a frame before startup timeout."
    )


def main() -> int:
    args = parse_args()
    if args.startup_timeout_seconds <= 0:
        raise ValueError("--startup-timeout-seconds must be positive")

    if not args.no_auto_loop and not args.no_viewer_stream:
        print(f"Tracking viewer stream: ws://{args.host}:{args.port}", flush=True)
    print("Starting tracking stack components:", flush=True)
    perception_command = _perception_command(args)
    print(f"- perception: {' '.join(perception_command)}", flush=True)
    if args.init_text not in (None, ""):
        print(f"- init-text: {args.init_text}", flush=True)

    processes: List[subprocess.Popen] = []
    try:
        state_root = (ROOT / args.state_root).resolve()
        previous_active_session_id = None
        if not args.session_id:
            previous_active_session_id = _active_session_id(state_root)

        perception_process = subprocess.Popen(perception_command, cwd=ROOT)
        processes.append(perception_process)

        print("Waiting for the first perception frame...", flush=True)
        try:
            started_session_id = _wait_for_started_session(
                args=args,
                perception_process=perception_process,
                previous_active_session_id=previous_active_session_id,
            )
        except (RuntimeError, TimeoutError) as exc:
            print(str(exc), flush=True)
            _terminate_processes(processes)
            return 1
        print(f"Perception ready on session {started_session_id}", flush=True)

        if args.init_text not in (None, ""):
            init_command = _chat_command(
                args,
                session_id=started_session_id,
                text=str(args.init_text),
            )
            print(f"- init-chat: {' '.join(init_command)}", flush=True)
            init_completed = subprocess.run(
                init_command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            if init_completed.stdout.strip():
                print(init_completed.stdout.strip(), flush=True)
            if init_completed.returncode != 0:
                if init_completed.stderr.strip():
                    print(init_completed.stderr.strip(), flush=True)
                _terminate_processes(processes)
                return init_completed.returncode

        if not args.no_auto_loop:
            loop_command = _loop_command_for_session(args, session_id=started_session_id)
            print(f"- tracking-runtime: {' '.join(loop_command)}", flush=True)
            processes.append(subprocess.Popen(loop_command, cwd=ROOT))

        while True:
            for label, process in zip(
                ["perception", *([] if args.no_auto_loop else ["tracking-runtime"])],
                processes,
            ):
                return_code = process.poll()
                if return_code is None:
                    continue
                print(f"{label} exited with code {return_code}", flush=True)
                _terminate_processes(processes)
                return return_code
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopping tracking stack...", flush=True)
        _terminate_processes(processes)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
