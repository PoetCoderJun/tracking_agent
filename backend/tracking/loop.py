from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

from agent.session_store import AgentSessionStore
from backend.tracking.bootstrap import float_env_value, load_tracking_env_values
from backend.tracking.deterministic import (
    apply_processed_tracking_payload,
    process_tracking_request_direct,
    schedule_bound_tracking_memory_rewrite as _schedule_bound_tracking_memory_rewrite,
)
from backend.perception.service import LocalPerceptionService
from backend.perception.stream import generate_request_id
from backend.persistence import resolve_session_id
from backend.project_paths import resolve_project_path
from backend.tracking.context import tracking_state_snapshot

TRACKING_SKILL_NAME = "tracking"


def parse_args() -> argparse.Namespace:
    bootstrap_parser = argparse.ArgumentParser(add_help=False)
    bootstrap_parser.add_argument("--env-file", default=".ENV")
    bootstrap_args, _ = bootstrap_parser.parse_known_args()
    env_values = load_tracking_env_values(bootstrap_args.env_file)

    parser = argparse.ArgumentParser(
        description=(
            "Tracking loop. Polls tracking session state and dispatches periodic deterministic "
            "track turns when an active target already exists."
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
    parser.add_argument("--env-file", default=bootstrap_args.env_file)
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    parser.add_argument("--continue-text", default="继续跟踪")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=float_env_value(env_values, "QUERY_INTERVAL_SECONDS", 3.0),
    )
    parser.add_argument(
        "--recovery-interval-seconds",
        type=float,
        default=float_env_value(env_values, "TRACKING_RECOVERY_INTERVAL_SECONDS", 1.0),
    )
    parser.add_argument(
        "--idle-sleep-seconds",
        type=float,
        default=float_env_value(env_values, "TRACKING_IDLE_SLEEP_SECONDS", 3.0),
    )
    parser.add_argument(
        "--presence-check-seconds",
        type=float,
        default=float_env_value(env_values, "TRACKING_PRESENCE_CHECK_SECONDS", 1.0),
    )
    parser.add_argument(
        "--rewrite-interval-seconds",
        type=float,
        default=float_env_value(env_values, "TRACKING_MEMORY_REWRITE_INTERVAL_SECONDS", 2.0),
    )
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument(
        "--stop-file",
        default=None,
        help="Optional file path. When this file exists, the loop exits after the current turn.",
    )
    return parser.parse_args()


def _sessions_from_args(args: argparse.Namespace) -> AgentSessionStore:
    return AgentSessionStore(
        state_root=resolve_project_path(args.state_root),
        frame_buffer_size=args.frame_buffer_size,
    )


def _tracking_state(context: Any) -> Dict[str, Any]:
    return tracking_state_snapshot((context.skills.get(TRACKING_SKILL_NAME) or {}))


def _has_active_target(tracking_state: Dict[str, Any]) -> bool:
    return (
        tracking_state.get("latest_target_id") not in (None, "", [])
        and tracking_state.get("latest_confirmed_frame_path") not in (None, "", [])
    )


def _waiting_for_user(tracking_state: Dict[str, Any]) -> bool:
    pending_question = tracking_state.get("pending_question")
    if pending_question in (None, ""):
        return False
    return str(pending_question).strip() != ""


def _latest_frame(context: Any) -> Dict[str, Any]:
    latest_observation = LocalPerceptionService(Path(context.state_paths["state_root"])).latest_camera_observation(
        session_id=context.session_id,
    )
    if latest_observation is None:
        return {}
    payload = dict(latest_observation.get("payload") or {})
    meta = dict(latest_observation.get("meta") or {})
    return {
        "frame_id": str(payload.get("frame_id", latest_observation.get("id", ""))).strip(),
        "timestamp_ms": int(latest_observation.get("ts_ms", 0)),
        "image_path": str(payload.get("image_path", "")).strip(),
        "detections": list(meta.get("detections") or []),
    }


def _perception_stream_status(context: Any) -> Dict[str, Any]:
    perception = LocalPerceptionService(Path(context.state_paths["state_root"])).read_snapshot(context.session_id)
    return dict(perception.get("stream_status") or {})


def _latest_target_id(tracking_state: Dict[str, Any]) -> int | None:
    target_id = tracking_state.get("latest_target_id")
    if target_id in (None, "", []):
        return None
    return int(target_id)


def _track_id_present_in_frame(frame: Dict[str, Any], target_id: int | None) -> bool:
    if target_id is None:
        return False
    for detection in list(frame.get("detections") or []):
        try:
            if int(detection.get("track_id")) == int(target_id):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _bound_detection(frame: Dict[str, Any], target_id: int | None) -> Dict[str, Any] | None:
    if target_id is None:
        return None
    for detection in list(frame.get("detections") or []):
        try:
            if int(detection.get("track_id")) == int(target_id):
                return dict(detection)
        except (TypeError, ValueError):
            continue
    return None


def _frame_track_ids(frame: Dict[str, Any]) -> set[int]:
    track_ids: set[int] = set()
    for detection in list(frame.get("detections") or []):
        try:
            track_ids.add(int(detection.get("track_id")))
        except (TypeError, ValueError):
            continue
    return track_ids


def _non_target_track_ids(frame: Dict[str, Any], target_id: int | None) -> set[int]:
    track_ids = _frame_track_ids(frame)
    if target_id is not None:
        track_ids.discard(int(target_id))
    return track_ids


def _next_dispatch_deadline(
    current_deadline: float | None,
    *,
    interval_seconds: float,
    now: float,
) -> float:
    if current_deadline is None:
        return now + interval_seconds
    return max(current_deadline + interval_seconds, now)


def _bound_status_signature(frame: Dict[str, Any], target_id: int | None) -> tuple[str | None, int | None]:
    return (None if not frame else frame.get("frame_id"), target_id)


def _stop_requested(stop_file: str | None) -> bool:
    if stop_file in (None, ""):
        return False
    return resolve_project_path(stop_file).exists()


def _should_schedule_rewrite(
    *,
    next_rewrite_at: float | None,
    now: float,
) -> bool:
    if next_rewrite_at is None:
        return True
    return now >= next_rewrite_at


def _stream_completed(stream_status: Dict[str, Any]) -> bool:
    return str(stream_status.get("status", "")).strip() == "completed"


def _should_request_track_for_frame(*, latest_frame_id: str | None, last_track_frame_id: str | None) -> bool:
    return latest_frame_id not in (None, "") and latest_frame_id != last_track_frame_id


def _schedule_bound_memory_rewrite(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    tracking_state: Dict[str, Any],
    frame: Dict[str, Any],
    detection: Dict[str, Any],
    env_file: Path,
    artifacts_root: Path,
) -> bool:
    return _schedule_bound_tracking_memory_rewrite(
        sessions=sessions,
        session_id=session_id,
        tracking_state=tracking_state,
        frame=frame,
        detection=detection,
        env_file=env_file,
        artifacts_root=artifacts_root,
    )


def main() -> int:
    args = parse_args()
    if args.interval_seconds <= 0:
        raise ValueError("--interval-seconds must be positive")
    if args.recovery_interval_seconds <= 0:
        raise ValueError("--recovery-interval-seconds must be positive")
    if args.idle_sleep_seconds <= 0:
        raise ValueError("--idle-sleep-seconds must be positive")
    if args.presence_check_seconds <= 0:
        raise ValueError("--presence-check-seconds must be positive")
    if args.rewrite_interval_seconds <= 0:
        raise ValueError("--rewrite-interval-seconds must be positive")
    if args.max_turns is not None and args.max_turns <= 0:
        raise ValueError("--max-turns must be positive when provided")

    sessions = _sessions_from_args(args)
    env_file = resolve_project_path(args.env_file)
    artifacts_root = resolve_project_path(args.artifacts_root)
    dispatched_turns = 0
    next_dispatch_at: float | None = None
    next_rewrite_at: float | None = None
    missing_target_id_for_track: int | None = None
    excluded_track_ids: set[int] = set()
    last_bound_signature: tuple[str | None, int | None] | None = None
    last_track_frame_id: str | None = None

    while True:
        if _stop_requested(args.stop_file):
            return 0

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

        context = sessions.load(session_id, device_id=args.device_id)
        tracking_state = _tracking_state(context)
        stream_status = _perception_stream_status(context)
        if not _has_active_target(tracking_state):
            next_dispatch_at = None
            next_rewrite_at = None
            missing_target_id_for_track = None
            excluded_track_ids.clear()
            last_bound_signature = None
            last_track_frame_id = None
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
            next_dispatch_at = None
            next_rewrite_at = None
            missing_target_id_for_track = None
            excluded_track_ids.clear()
            last_bound_signature = None
            last_track_frame_id = None
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

        latest_frame = _latest_frame(context)
        current_target_id = _latest_target_id(tracking_state)
        bound_detection = _bound_detection(latest_frame, current_target_id)
        if bound_detection is not None:
            next_dispatch_at = None
            missing_target_id_for_track = None
            last_track_frame_id = None
            excluded_track_ids.update(_non_target_track_ids(latest_frame, current_target_id))
            current_signature = _bound_status_signature(latest_frame, current_target_id)
            if current_signature != last_bound_signature:
                print(
                    json.dumps(
                        {
                            "session_id": session_id,
                            "status": "tracking_bound",
                            "target_id": current_target_id,
                            "frame_id": latest_frame.get("frame_id"),
                        },
                        ensure_ascii=True,
                    ),
                    flush=True,
                )
                last_bound_signature = current_signature
            if _stream_completed(stream_status):
                print(
                    json.dumps(
                        {
                            "session_id": session_id,
                            "status": "completed",
                            "reason": "Perception stream completed.",
                            "frame_id": latest_frame.get("frame_id"),
                        },
                        ensure_ascii=True,
                    ),
                    flush=True,
                )
                return 0
            now = time.monotonic()
            if _should_schedule_rewrite(
                next_rewrite_at=next_rewrite_at,
                now=now,
            ):
                if _schedule_bound_memory_rewrite(
                    sessions=sessions,
                    session_id=session_id,
                    tracking_state=tracking_state,
                    frame=latest_frame,
                    detection=bound_detection,
                    env_file=env_file,
                    artifacts_root=artifacts_root,
                ):
                    next_rewrite_at = now + args.rewrite_interval_seconds
            time.sleep(min(args.idle_sleep_seconds, args.presence_check_seconds))
            continue

        now = time.monotonic()
        last_bound_signature = None
        next_rewrite_at = None
        latest_frame_id = str(latest_frame.get("frame_id", "")).strip() or None
        stream_completed = _stream_completed(stream_status)
        if stream_completed and latest_frame_id is not None and latest_frame_id == last_track_frame_id:
            print(
                json.dumps(
                    {
                        "session_id": session_id,
                        "status": "completed",
                        "reason": "Perception stream completed.",
                        "frame_id": latest_frame_id,
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )
            return 0
        if missing_target_id_for_track != current_target_id:
            missing_target_id_for_track = current_target_id
            next_dispatch_at = now
            last_track_frame_id = None
        elif next_dispatch_at is None:
            next_dispatch_at = now
        if now < next_dispatch_at:
            time.sleep(min(args.recovery_interval_seconds, args.presence_check_seconds, next_dispatch_at - now))
            continue
        if latest_frame_id is None:
            time.sleep(min(args.recovery_interval_seconds, args.presence_check_seconds))
            continue
        if not _should_request_track_for_frame(
            latest_frame_id=latest_frame_id,
            last_track_frame_id=last_track_frame_id,
        ):
            if stream_completed:
                print(
                    json.dumps(
                        {
                            "session_id": session_id,
                            "status": "completed",
                            "reason": "Perception stream completed.",
                            "frame_id": latest_frame_id,
                        },
                        ensure_ascii=True,
                    ),
                    flush=True,
                )
                return 0
            time.sleep(min(args.recovery_interval_seconds, args.presence_check_seconds))
            continue

        request_id = generate_request_id(prefix="track_loop")
        payload = process_tracking_request_direct(
            sessions=sessions,
            session_id=session_id,
            device_id=args.device_id,
            text=args.continue_text,
            request_id=request_id,
            env_file=env_file,
            artifacts_root=artifacts_root,
            excluded_track_ids=sorted(excluded_track_ids),
            apply_processed_payload=lambda *, session_id, pi_payload, env_file: apply_processed_tracking_payload(
                sessions=sessions,
                session_id=session_id,
                pi_payload=pi_payload,
                env_file=env_file,
            ),
        )
        session_result = dict(payload.get("session_result") or {})
        selected_target_id = session_result.get("target_id")
        if selected_target_id not in (None, "", []):
            excluded_track_ids.update(_non_target_track_ids(latest_frame, int(selected_target_id)))
        else:
            excluded_track_ids.update(_frame_track_ids(latest_frame))
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
        last_track_frame_id = latest_frame_id
        if args.max_turns is not None and dispatched_turns >= args.max_turns:
            return 0
        next_dispatch_at = _next_dispatch_deadline(
            next_dispatch_at,
            interval_seconds=args.recovery_interval_seconds,
            now=time.monotonic(),
        )


if __name__ == "__main__":
    raise SystemExit(main())
