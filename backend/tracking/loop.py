from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

from backend.tracking.env import float_env_value, load_tracking_env_values
from backend.tracking.deterministic import (
    apply_processed_tracking_payload,
    process_tracking_request_direct,
    schedule_bound_tracking_memory_rewrite as _schedule_bound_tracking_memory_rewrite,
    tracking_missing_reference_views,
)
from backend.perception.service import LocalPerceptionService
from backend.perception.stream import generate_request_id
from backend.persistence import resolve_session_id
from backend.project_paths import resolve_project_path
from backend.runtime_session import AgentSessionStore
from backend.tracking.context import (
    TRACKING_LIFECYCLE_BOUND,
    TRACKING_LIFECYCLE_INACTIVE,
    TRACKING_LIFECYCLE_RUNNING,
    TRACKING_LIFECYCLE_SEEKING,
    TRACKING_LIFECYCLE_STOPPED,
    tracking_state_snapshot,
)

TRACKING_SKILL_NAME = "tracking"
BOUND_REVIEW_FAST_WINDOW_FRAMES = 3
BOUND_REVIEW_SLOW_INTERVAL_FRAMES = 8
BOUND_REWRITE_MIN_STABLE_FRAMES = 3
DEFAULT_SUPERVISOR_POLL_SECONDS = 0.25


def parse_args() -> argparse.Namespace:
    bootstrap_parser = argparse.ArgumentParser(add_help=False)
    bootstrap_parser.add_argument("--env-file", default=".ENV")
    bootstrap_args, _ = bootstrap_parser.parse_known_args()
    env_values = load_tracking_env_values(bootstrap_args.env_file)

    parser = argparse.ArgumentParser(
        description=(
            "Tracking debug adapter. Runs one supervisor-style tracking step against the current session."
        )
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, follows the current active session.",
    )
    parser.add_argument("--device-id", default="robot_01")
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
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
    return AgentSessionStore(state_root=resolve_project_path(args.state_root))


def _tracking_state(context: Any) -> Dict[str, Any]:
    return tracking_state_snapshot((context.skills.get(TRACKING_SKILL_NAME) or {}))


def _has_active_target(tracking_state: Dict[str, Any]) -> bool:
    return tracking_state.get("latest_target_id") not in (None, "", [])


def _waiting_for_user(tracking_state: Dict[str, Any]) -> bool:
    pending_question = tracking_state.get("pending_question")
    if pending_question in (None, ""):
        return False
    return str(pending_question).strip() != ""


def _latest_frame(context: Any) -> Dict[str, Any]:
    latest_observation = LocalPerceptionService(Path(context.state_paths["state_root"])).latest_camera_observation()
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
    perception = LocalPerceptionService(Path(context.state_paths["state_root"])).read_snapshot()
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


def _has_competing_detections(frame: Dict[str, Any], target_id: int | None) -> bool:
    return bool(_non_target_track_ids(frame, target_id))


def _should_review_bound_target(
    *,
    has_competing_detections: bool,
    stable_bound_frames: int,
    latest_frame_id: str | None,
    last_review_frame_id: str | None,
) -> bool:
    if not has_competing_detections:
        return False
    if not _should_request_track_for_frame(
        latest_frame_id=latest_frame_id,
        last_track_frame_id=last_review_frame_id,
    ):
        return False
    if stable_bound_frames <= BOUND_REVIEW_FAST_WINDOW_FRAMES:
        return True
    return (stable_bound_frames - BOUND_REVIEW_FAST_WINDOW_FRAMES) % BOUND_REVIEW_SLOW_INTERVAL_FRAMES == 0


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


def _next_rewrite_delay_seconds(
    *,
    rewrite_interval_seconds: float,
    state_root: Path,
    session_id: str,
    tracking_state: Dict[str, Any],
) -> float:
    _ = tracking_state
    if tracking_missing_reference_views(state_root=state_root, session_id=session_id):
        return min(rewrite_interval_seconds, 1.0)
    return rewrite_interval_seconds


def _should_allow_bound_rewrite(
    *,
    review_confirmed: bool,
    stable_bound_frames: int,
) -> bool:
    return review_confirmed and stable_bound_frames >= BOUND_REWRITE_MIN_STABLE_FRAMES


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


def _tracking_status_patch(
    *,
    lifecycle_status: str,
    latest_frame_id: str | None = None,
    next_tracking_turn_at: float | None = None,
    last_trigger: str | None = None,
    stop_reason: str | None = None,
) -> Dict[str, Any]:
    patch: Dict[str, Any] = {"lifecycle_status": lifecycle_status}
    if latest_frame_id not in (None, ""):
        patch["last_seen_frame_id"] = latest_frame_id
    if next_tracking_turn_at is not None:
        patch["next_tracking_turn_at"] = next_tracking_turn_at
    if last_trigger not in (None, ""):
        patch["last_trigger"] = last_trigger
    if stop_reason not in (None, ""):
        patch["stop_reason"] = stop_reason
    return patch


def supervisor_tracking_step(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    device_id: str,
    env_file: Path,
    artifacts_root: Path,
    owner_id: str,
    continue_text: str = "继续跟踪",
    interval_seconds: float = 3.0,
) -> Dict[str, Any]:
    context = sessions.load(session_id, device_id=device_id)
    tracking_state = _tracking_state(context)
    stream_status = _perception_stream_status(context)
    latest_frame = _latest_frame(context)
    latest_frame_id = str(latest_frame.get("frame_id", "")).strip() or None
    current_target_id = _latest_target_id(tracking_state)
    last_completed_frame_id = str(tracking_state.get("last_completed_frame_id", "") or "").strip()
    due_at = tracking_state.get("next_tracking_turn_at")
    try:
        due_at_seconds = float(due_at)
    except (TypeError, ValueError):
        due_at_seconds = 0.0
    now_seconds = time.time()

    if not _has_active_target(tracking_state):
        sessions.patch_skill_state(
            session_id,
            skill_name=TRACKING_SKILL_NAME,
            patch=_tracking_status_patch(
                lifecycle_status=TRACKING_LIFECYCLE_INACTIVE,
                latest_frame_id=latest_frame_id,
                stop_reason="no_active_target",
            ),
        )
        return {"status": "idle", "reason": "no_active_target", "sleep_seconds": DEFAULT_SUPERVISOR_POLL_SECONDS}

    if _waiting_for_user(tracking_state):
        sessions.patch_skill_state(
            session_id,
            skill_name=TRACKING_SKILL_NAME,
            patch=_tracking_status_patch(
                lifecycle_status=TRACKING_LIFECYCLE_SEEKING,
                latest_frame_id=latest_frame_id,
                stop_reason="waiting_for_user",
            ),
        )
        return {"status": "waiting", "reason": "waiting_for_user", "sleep_seconds": DEFAULT_SUPERVISOR_POLL_SECONDS}

    target_present = _track_id_present_in_frame(latest_frame, current_target_id)
    should_track = False
    trigger = ""
    if latest_frame_id is not None and not target_present and latest_frame_id != last_completed_frame_id:
        should_track = True
        trigger = "missing"
    elif latest_frame_id is not None and now_seconds >= due_at_seconds and latest_frame_id != last_completed_frame_id:
        should_track = True
        trigger = "cadence"

    if not should_track:
        sessions.patch_skill_state(
            session_id,
            skill_name=TRACKING_SKILL_NAME,
            patch=_tracking_status_patch(
                lifecycle_status=TRACKING_LIFECYCLE_BOUND if target_present else TRACKING_LIFECYCLE_SEEKING,
                latest_frame_id=latest_frame_id,
            ),
        )
        return {
            "status": "bound" if target_present else "seeking",
            "target_present": target_present,
            "sleep_seconds": DEFAULT_SUPERVISOR_POLL_SECONDS,
        }

    request_id = generate_request_id(prefix="track_supervisor")
    acquired = sessions.acquire_turn(
        session_id=session_id,
        owner_id=owner_id,
        turn_kind="tracking",
        request_id=request_id,
        device_id=device_id,
        wait=False,
    )
    if acquired is None:
        return {"status": "busy", "reason": "lease_held", "sleep_seconds": DEFAULT_SUPERVISOR_POLL_SECONDS}

    sessions.patch_skill_state(
        session_id,
        skill_name=TRACKING_SKILL_NAME,
        patch=_tracking_status_patch(
            lifecycle_status=TRACKING_LIFECYCLE_RUNNING,
            latest_frame_id=latest_frame_id,
            last_trigger=trigger,
        ),
    )
    try:
        payload = process_tracking_request_direct(
            sessions=sessions,
            session_id=session_id,
            device_id=device_id,
            text=continue_text,
            request_id=request_id,
            env_file=env_file,
            artifacts_root=artifacts_root,
            append_chat_request=False,
            apply_tracking_payload=lambda *, session_id, pi_payload, env_file: apply_processed_tracking_payload(
                sessions=sessions,
                session_id=session_id,
                pi_payload=pi_payload,
                env_file=env_file,
            ),
            acquire_turn=False,
            turn_owner_id=owner_id,
            wait_for_turn=False,
            turn_kind="tracking",
        )
    finally:
        sessions.release_turn(
            session_id=session_id,
            owner_id=owner_id,
            request_id=request_id,
            device_id=device_id,
        )

    result = dict(payload.get("session_result") or {})
    sessions.patch_skill_state(
        session_id,
        skill_name=TRACKING_SKILL_NAME,
        patch={
            "last_completed_frame_id": str(result.get("frame_id", "") or latest_frame_id or ""),
            "last_trigger": trigger,
            "next_tracking_turn_at": time.time() + interval_seconds,
            "lifecycle_status": TRACKING_LIFECYCLE_BOUND if bool(result.get("found", False)) else TRACKING_LIFECYCLE_SEEKING,
        },
    )
    status = "tracked" if bool(result.get("found", False)) else "waiting"
    if _stream_completed(stream_status):
        status = "completed"
    return {
        "status": status,
        "request_id": request_id,
        "trigger": trigger,
        "payload": payload,
        "sleep_seconds": DEFAULT_SUPERVISOR_POLL_SECONDS,
    }


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
        return 0

    payload = supervisor_tracking_step(
        sessions=sessions,
        session_id=session_id,
        device_id=args.device_id,
        env_file=env_file,
        artifacts_root=artifacts_root,
        owner_id=f"tracking-loop-debug:{session_id}",
        continue_text=args.continue_text,
        interval_seconds=args.interval_seconds,
    )
    print(json.dumps(payload, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
