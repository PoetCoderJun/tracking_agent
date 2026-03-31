#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List, Optional

from backend.agent.runtime import LocalAgentRuntime
from backend.config import parse_dotenv
from backend.perception.service import LocalPerceptionService
from backend.project_paths import resolve_project_path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMERA_SOURCE = "camera"


def _float_env_value(values: dict[str, str], key: str, default: float) -> float:
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
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=None,
        help="Legacy override. When set, applies to both perception and query intervals.",
    )
    parser.add_argument(
        "--perception-interval-seconds",
        type=float,
        default=_float_env_value(env_values, "PERCEPTION_INTERVAL_SECONDS", 1.0),
    )
    parser.add_argument(
        "--query-interval-seconds",
        type=float,
        default=_float_env_value(env_values, "QUERY_INTERVAL_SECONDS", 3.0),
    )
    parser.add_argument(
        "--recovery-interval-seconds",
        type=float,
        default=_float_env_value(env_values, "TRACKING_RECOVERY_INTERVAL_SECONDS", 1.0),
    )
    parser.add_argument("--realtime-playback", action="store_true")
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--max-event-log-lines", type=int, default=300)
    parser.add_argument("--person-class-id", type=int, default=0)
    parser.add_argument("--env-file", default=bootstrap_args.env_file)
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    parser.add_argument("--pi-binary", default="pi")
    parser.add_argument("--continue-text", default="继续跟踪")
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
    parser.add_argument(
        "--init-text",
        required=True,
        help="Initial tracking instruction that must confirm the first target before polling begins.",
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
        "--shutdown-grace-seconds",
        type=float,
        default=60.0,
        help="How long to let the tracking runtime finish its current turn after perception ends.",
    )
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
    args = parser.parse_args()
    if args.interval_seconds is not None:
        args.perception_interval_seconds = args.interval_seconds
        args.query_interval_seconds = args.interval_seconds
    return args


def _append_optional(command: List[str], flag: str, value: object) -> None:
    if value in (None, ""):
        return
    command.extend([flag, str(value)])


def _init_pause_file(args: argparse.Namespace) -> Optional[Path]:
    if args.init_text in (None, ""):
        return None
    return resolve_project_path(args.state_root) / "tracking_stack_init.pause"


def _loop_stop_file(args: argparse.Namespace, *, session_id: str) -> Path:
    return resolve_project_path(args.state_root) / "sessions" / session_id / "tracking_loop.stop"


def _perception_command(args: argparse.Namespace) -> List[str]:
    pause_file = _init_pause_file(args)
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
        str(args.perception_interval_seconds),
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
    _append_optional(command, "--pause-after-first-event-file", pause_file)
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
        str(args.query_interval_seconds),
        "--recovery-interval-seconds",
        str(args.recovery_interval_seconds),
        "--idle-sleep-seconds",
        str(args.idle_sleep_seconds),
        "--presence-check-seconds",
        str(args.presence_check_seconds),
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


def _tracking_runtime_command(args: argparse.Namespace, *, started_session_id: str) -> List[str]:
    runtime_session_id = started_session_id if args.session_id else None
    command = _loop_command_for_session(args, session_id=runtime_session_id)
    command.extend(["--stop-file", str(_loop_stop_file(args, session_id=started_session_id))])
    if _use_standalone_viewer_stream(args) and "--no-viewer-stream" not in command:
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


def _use_standalone_viewer_stream(args: argparse.Namespace) -> bool:
    return (
        not args.no_auto_loop
        and not args.no_viewer_stream
        and args.init_text not in (None, "")
    )


def _json_payload_from_stdout(stdout: str) -> Optional[dict[str, Any]]:
    for raw_line in reversed(stdout.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _init_turn_confirmed(payload: Optional[dict[str, Any]]) -> bool:
    if not isinstance(payload, dict):
        return False
    if str(payload.get("status", "")).strip() != "processed":
        return False

    session_result = payload.get("session_result")
    if not isinstance(session_result, dict):
        return False

    if bool(session_result.get("needs_clarification", False)):
        return False
    if session_result.get("target_id") in (None, ""):
        return False

    found = session_result.get("found")
    if found is None:
        found = (payload.get("tool_output") or {}).get("found")
    return bool(found)


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
    return len(LocalPerceptionService(state_root=state_root).recent_camera_observations(session_id=session_id))


def _first_session_frame_snapshot(state_root: Path, session_id: str) -> Optional[dict[str, Any]]:
    frames = [
        {
            "frame_id": str((item.get("payload") or {}).get("frame_id", item.get("id", ""))).strip(),
            "timestamp_ms": int(item.get("ts_ms", 0)),
            "image_path": str((item.get("payload") or {}).get("image_path", "")).strip(),
            "detections": list((item.get("meta") or {}).get("detections") or []),
        }
        for item in LocalPerceptionService(state_root=state_root).recent_camera_observations(
            session_id=session_id
        )
    ]
    if not frames:
        return None

    frame = dict(frames[0])
    detections: list[dict[str, Any]] = []
    for detection in frame.get("detections") or []:
        detections.append(
            {
                "track_id": int(detection["track_id"]),
                "bbox": [int(value) for value in detection["bbox"]],
                "score": float(detection.get("score", 1.0)),
                "label": str(detection.get("label", "person")),
            }
        )

    return {
        "frame_id": str(frame.get("frame_id", "")).strip(),
        "timestamp_ms": int(frame.get("timestamp_ms", 0)),
        "image_path": str(frame.get("image_path", "")).strip(),
        "detections": detections,
    }


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
    if args.perception_interval_seconds <= 0:
        raise ValueError("--perception-interval-seconds must be positive")
    if args.query_interval_seconds <= 0:
        raise ValueError("--query-interval-seconds must be positive")
    if args.idle_sleep_seconds <= 0:
        raise ValueError("--idle-sleep-seconds must be positive")
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
    process_labels: List[str] = []
    pause_file = _init_pause_file(args)
    loop_stop_file: Optional[Path] = None
    try:
        state_root = resolve_project_path(args.state_root)
        if pause_file is not None:
            pause_file.parent.mkdir(parents=True, exist_ok=True)
            pause_file.write_text("pause", encoding="utf-8")
        previous_active_session_id = None
        if not args.session_id:
            previous_active_session_id = _active_session_id(state_root)

        perception_process = subprocess.Popen(perception_command, cwd=ROOT)
        processes.append(perception_process)
        process_labels.append("perception")

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

        if _use_standalone_viewer_stream(args):
            viewer_command = _viewer_command(args)
            print(f"- viewer-stream: {' '.join(viewer_command)}", flush=True)
            processes.append(subprocess.Popen(viewer_command, cwd=ROOT))
            process_labels.append("viewer-stream")

        if args.init_text not in (None, ""):
            runtime = LocalAgentRuntime(state_root=state_root)
            init_frame_snapshot = _first_session_frame_snapshot(state_root, started_session_id)
            if init_frame_snapshot is not None:
                runtime.update_skill_cache(
                    started_session_id,
                    skill_name="tracking",
                    payload={"init_frame_snapshot": init_frame_snapshot},
                )
            init_command = _chat_command(
                args,
                session_id=started_session_id,
                text=str(args.init_text),
            )
            print(f"- init-chat: {' '.join(init_command)}", flush=True)
            try:
                init_completed = subprocess.run(
                    init_command,
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            finally:
                if init_frame_snapshot is not None:
                    runtime.update_skill_cache(
                        started_session_id,
                        skill_name="tracking",
                        payload={"init_frame_snapshot": None},
                    )
            if init_completed.stdout.strip():
                print(init_completed.stdout.strip(), flush=True)
            if init_completed.returncode != 0:
                if init_completed.stderr.strip():
                    print(init_completed.stderr.strip(), flush=True)
                if pause_file is not None and pause_file.exists():
                    pause_file.unlink()
                _terminate_processes(processes)
                return init_completed.returncode
            init_payload = _json_payload_from_stdout(init_completed.stdout)
            if not _init_turn_confirmed(init_payload):
                print(
                    "Initial target was not confirmed. Stopping tracking stack before polling loop starts.",
                    flush=True,
                )
                if pause_file is not None and pause_file.exists():
                    pause_file.unlink()
                _terminate_processes(processes)
                return 1
            if pause_file is not None and pause_file.exists():
                pause_file.unlink()

        if not args.no_auto_loop:
            loop_stop_file = _loop_stop_file(args, session_id=started_session_id)
            loop_stop_file.parent.mkdir(parents=True, exist_ok=True)
            loop_stop_file.unlink(missing_ok=True)
            loop_command = _tracking_runtime_command(args, started_session_id=started_session_id)
            print(f"- tracking-runtime: {' '.join(loop_command)}", flush=True)
            processes.append(subprocess.Popen(loop_command, cwd=ROOT))
            process_labels.append("tracking-runtime")

        while True:
            for label, process in zip(process_labels, processes):
                return_code = process.poll()
                if return_code is None:
                    continue
                print(f"{label} exited with code {return_code}", flush=True)
                if (
                    label == "perception"
                    and return_code == 0
                    and loop_stop_file is not None
                    and "tracking-runtime" in process_labels
                ):
                    loop_stop_file.write_text("stop", encoding="utf-8")
                    deadline = time.time() + args.shutdown_grace_seconds
                    while time.time() < deadline:
                        all_stopped = True
                        for pending_label, pending_process in zip(process_labels, processes):
                            if pending_label == "perception":
                                continue
                            pending_return_code = pending_process.poll()
                            if pending_return_code is None:
                                all_stopped = False
                                continue
                            if pending_return_code != 0:
                                _terminate_processes(processes)
                                return pending_return_code
                        if all_stopped:
                            _terminate_processes(processes)
                            return 0
                        time.sleep(0.5)
                    _terminate_processes(processes)
                    return 0
                _terminate_processes(processes)
                return return_code
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopping tracking stack...", flush=True)
        _terminate_processes(processes)
        return 0
    finally:
        if pause_file is not None and pause_file.exists():
            pause_file.unlink()
        if loop_stop_file is not None and loop_stop_file.exists():
            loop_stop_file.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
