#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agent.runner import PiAgentRunner
from backend.perception.stream import generate_request_id
from backend.persistence import resolve_session_id
from backend.project_paths import resolve_project_path
from skills.tracking.viewer_stream import TrackingViewerStreamServer

TRACKING_SKILL_NAME = "tracking"
ACTIVE_TRACKING_FIELDS = (
    "target_description",
    "latest_memory",
    "latest_target_id",
    "latest_target_crop",
    "latest_confirmed_frame_path",
    "memory",
    "target_id",
    "crop_path",
    "initialized_frame",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Tracking loop. Polls tracking session state and dispatches periodic chat turns "
            "when an active target already exists."
        )
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, follows the current active session.",
    )
    parser.add_argument("--device-id", default="robot_01")
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--frame-buffer-size", type=int, default=3)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    parser.add_argument("--pi-binary", default="pi")
    parser.add_argument("--continue-text", default="继续跟踪")
    parser.add_argument("--interval-seconds", type=float, default=3.0)
    parser.add_argument("--idle-sleep-seconds", type=float, default=1.0)
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--viewer-host", default="127.0.0.1")
    parser.add_argument("--viewer-port", type=int, default=8765)
    parser.add_argument("--viewer-poll-interval", type=float, default=1.0)
    parser.add_argument(
        "--no-viewer-stream",
        action="store_true",
        help="Disable the websocket stream normally coupled to the tracking runtime loop.",
    )
    return parser.parse_args()


def _runner_from_args(args: argparse.Namespace) -> PiAgentRunner:
    return PiAgentRunner(
        state_root=resolve_project_path(args.state_root),
        frame_buffer_size=args.frame_buffer_size,
        pi_binary=str(args.pi_binary),
        enabled_skills=[TRACKING_SKILL_NAME],
    )


def _tracking_state(context: Any) -> Dict[str, Any]:
    state = dict((context.skill_cache.get(TRACKING_SKILL_NAME) or {}))
    if "latest_target_id" not in state and state.get("target_id") not in (None, ""):
        state["latest_target_id"] = state.get("target_id")
    if "latest_memory" not in state and state.get("memory") not in (None, ""):
        state["latest_memory"] = state.get("memory")
    if "latest_target_crop" not in state and state.get("crop_path") not in (None, ""):
        state["latest_target_crop"] = state.get("crop_path")
    return state


def _has_active_target(tracking_state: Dict[str, Any]) -> bool:
    return any(tracking_state.get(field) not in (None, "", []) for field in ACTIVE_TRACKING_FIELDS)


def _waiting_for_user(tracking_state: Dict[str, Any]) -> bool:
    pending_question = tracking_state.get("pending_question")
    if pending_question in (None, ""):
        pending_question = tracking_state.get("clarification_question")
    if pending_question in (None, ""):
        return False
    return str(pending_question).strip() != ""


def _start_viewer_stream(args: argparse.Namespace) -> threading.Thread | None:
    viewer_host = str(args.viewer_host or "").strip()
    if args.no_viewer_stream or not viewer_host:
        return None

    print(
        json.dumps(
            {
                "status": "viewer_stream_starting",
                "url": f"ws://{viewer_host}:{args.viewer_port}",
            },
            ensure_ascii=True,
        ),
        flush=True,
    )

    def _serve() -> None:
        server = TrackingViewerStreamServer(
            state_root=resolve_project_path(args.state_root),
            session_id=args.session_id,
            host=viewer_host,
            port=args.viewer_port,
            poll_interval=args.viewer_poll_interval,
        )
        try:
            asyncio.run(server.serve_forever())
        except OSError as exc:
            print(
                json.dumps(
                    {
                        "status": "viewer_stream_skipped",
                        "url": f"ws://{viewer_host}:{args.viewer_port}",
                        "reason": str(exc),
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
        except Exception as exc:  # pragma: no cover
            print(
                json.dumps(
                    {
                        "status": "viewer_stream_stopped",
                        "url": f"ws://{viewer_host}:{args.viewer_port}",
                        "reason": str(exc),
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )

    thread = threading.Thread(
        target=_serve,
        name="tracking-viewer-stream",
        daemon=True,
    )
    thread.start()
    return thread


def main() -> int:
    args = parse_args()
    if args.interval_seconds <= 0:
        raise ValueError("--interval-seconds must be positive")
    if args.idle_sleep_seconds <= 0:
        raise ValueError("--idle-sleep-seconds must be positive")
    if args.max_turns is not None and args.max_turns <= 0:
        raise ValueError("--max-turns must be positive when provided")
    if args.viewer_port <= 0:
        raise ValueError("--viewer-port must be positive")
    if args.viewer_poll_interval <= 0:
        raise ValueError("--viewer-poll-interval must be positive")

    runner = _runner_from_args(args)
    env_file = resolve_project_path(args.env_file)
    artifacts_root = resolve_project_path(args.artifacts_root)
    dispatched_turns = 0
    _start_viewer_stream(args)

    while True:
        session_id = resolve_session_id(
            state_root=resolve_project_path(args.state_root),
            session_id=args.session_id,
        )
        if session_id is None:
            print(
                json.dumps(
                    {
                        "session_id": None,
                        "status": "idle",
                        "reason": "No active session.",
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
            time.sleep(args.idle_sleep_seconds)
            continue

        context = runner.runtime.context(session_id, device_id=args.device_id)
        tracking_state = _tracking_state(context)
        if not _has_active_target(tracking_state):
            print(
                json.dumps(
                    {
                        "session_id": session_id,
                        "status": "idle",
                        "reason": "No active tracking target.",
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
            time.sleep(args.idle_sleep_seconds)
            continue

        if _waiting_for_user(tracking_state):
            print(
                json.dumps(
                    {
                        "session_id": session_id,
                        "status": "idle",
                        "reason": "Tracking is waiting for user clarification.",
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
            time.sleep(args.idle_sleep_seconds)
            continue

        request_id = generate_request_id(prefix="track_loop")
        payload = runner.process_chat_request(
            session_id=session_id,
            device_id=args.device_id,
            text=args.continue_text,
            request_id=request_id,
            env_file=env_file,
            artifacts_root=artifacts_root,
        )
        print(
            json.dumps(
                {
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": payload.get("status"),
                    "skill_name": payload.get("skill_name"),
                    "tool": payload.get("tool"),
                    "robot_response": payload.get("robot_response"),
                },
                ensure_ascii=True,
            ),
            flush=True,
        )

        dispatched_turns += 1
        if args.max_turns is not None and dispatched_turns >= args.max_turns:
            return 0
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
