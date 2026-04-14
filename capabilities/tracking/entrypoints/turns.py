from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from agent.project_paths import resolve_project_path
from agent.session import AgentSessionStore
from capabilities.tracking.agent import run_tracking_agent_turn
from capabilities.tracking.artifacts.crop import save_target_crop
from capabilities.tracking.policy.rewrite_memory import execute_rewrite_memory_tool
from capabilities.tracking.policy.select import (
    build_rewrite_memory_input,
    ensure_session_dirs,
    execute_select_tool,
    persist_reference_frame,
    rewrite_memory_frame_paths,
)
from capabilities.tracking.runtime.context import (
    build_tracking_init_context,
    normalize_tracking_state,
)
from capabilities.tracking.runtime.effects import (
    apply_tracking_decision,
    decision_from_select_output,
)
from capabilities.tracking.runtime.triggers import latest_tracking_frame
from capabilities.tracking.runtime.types import (
    TRIGGER_CHAT_INIT,
    TRIGGER_EVENT_REBIND,
    TrackingTrigger,
)
from capabilities.tracking.state.memory import read_tracking_memory_snapshot, write_tracking_memory_snapshot

TRACKING_SKILL_NAME = "tracking-init"
DEFAULT_PI_TURN_OWNER_ID = "pi"
DEFAULT_TRACKING_TURN_OWNER_ID = "tracking-supervisor"


def tracking_missing_reference_views(*, state_root: Path, session_id: str) -> list[str]:
    memory_snapshot = read_tracking_memory_snapshot(state_root=state_root, session_id=session_id)
    latest_memory = memory_snapshot["memory"]
    missing: list[str] = []
    if not str(memory_snapshot.get("front_crop_path", "") or "").strip() or not str(latest_memory.get("front_view", "") or "").strip():
        missing.append("front")
    if not str(memory_snapshot.get("back_crop_path", "") or "").strip() or not str(latest_memory.get("back_view", "") or "").strip():
        missing.append("back")
    return missing


def desired_reference_view_goal(*, state_root: Path, session_id: str) -> str:
    missing_views = tracking_missing_reference_views(state_root=state_root, session_id=session_id)
    if missing_views == ["front"]:
        return "front"
    if missing_views == ["back"]:
        return "back"
    if missing_views:
        return "any"
    return ""


def apply_tracking_rewrite_output(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    rewrite_output: Dict[str, Any],
) -> None:
    write_tracking_memory_snapshot(
        state_root=sessions.state_root,
        session_id=session_id,
        memory=rewrite_output["memory"],
        crop_path=rewrite_output.get("crop_path"),
        reference_view=rewrite_output.get("reference_view"),
        reset=str(rewrite_output.get("task", "")).strip() == "init",
    )


def tracking_rewrite_still_relevant(
    sessions: AgentSessionStore,
    *,
    session_id: str,
    target_id: int,
) -> bool:
    session = sessions.load(session_id)
    tracking_state = normalize_tracking_state(session.capabilities.get(TRACKING_SKILL_NAME))
    current_target_id = tracking_state.latest_target_id
    if current_target_id is None:
        return False
    return int(current_target_id) == int(target_id)


def schedule_tracking_memory_rewrite(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    rewrite_memory_input: Dict[str, Any],
    env_file: Path,
) -> None:
    crop_path = str(rewrite_memory_input.get("crop_path", "") or "").strip()
    frame_paths = [
        str(path).strip()
        for path in list(rewrite_memory_input.get("frame_paths") or [])
        if str(path).strip()
    ]
    if not crop_path or not frame_paths:
        return

    target_id = int(rewrite_memory_input["target_id"])
    if not tracking_rewrite_still_relevant(
        sessions,
        session_id=session_id,
        target_id=target_id,
    ):
        return

    session = sessions.load(session_id)
    rewrite_output = execute_rewrite_memory_tool(
        session_file=Path(session.state_paths["session_path"]),
        arguments=dict(rewrite_memory_input),
        env_file=env_file,
    )
    if not tracking_rewrite_still_relevant(
        sessions,
        session_id=session_id,
        target_id=target_id,
    ):
        return
    apply_tracking_rewrite_output(
        sessions=sessions,
        session_id=session_id,
        rewrite_output=rewrite_output,
    )


def schedule_bound_tracking_memory_rewrite(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    tracking_state: Dict[str, Any],
    frame: Dict[str, Any],
    detection: Dict[str, Any],
    env_file: Path,
    artifacts_root: Path,
) -> bool:
    image_path = str(frame.get("image_path", "")).strip()
    frame_id = str(frame.get("frame_id", "")).strip()
    if not image_path or not frame_id:
        return False

    target_id = tracking_state.get("latest_target_id")
    if target_id in (None, "", []):
        return False

    bbox = detection.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return False

    persisted_current_frame_path = resolve_project_path(image_path)
    if not persisted_current_frame_path.exists():
        return False

    session_dirs = ensure_session_dirs(artifacts_root, session_id)
    crop_path = session_dirs["crops_dir"] / f"{persisted_current_frame_path.stem}_id_{target_id}.jpg"
    save_target_crop(persisted_current_frame_path, bbox, crop_path)
    current_frame_reference_path = persist_reference_frame(
        persisted_current_frame_path,
        session_dirs["frames_dir"] / f"{persisted_current_frame_path.stem}.jpg",
    )
    schedule_tracking_memory_rewrite(
        sessions=sessions,
        session_id=session_id,
        rewrite_memory_input=build_rewrite_memory_input(
            behavior="track",
            crop_path=crop_path,
            frame_paths=rewrite_memory_frame_paths(
                behavior="track",
                current_frame_path=current_frame_reference_path,
            ),
            frame_id=frame_id,
            target_id=int(target_id),
            desired_reference_view=desired_reference_view_goal(
                state_root=sessions.state_root,
                session_id=session_id,
            ),
        ),
        env_file=env_file,
    )
    return True


def run_bound_tracking_memory_rewrite_sync(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    tracking_state: Dict[str, Any],
    frame: Dict[str, Any],
    detection: Dict[str, Any],
    env_file: Path,
    artifacts_root: Path,
) -> bool:
    image_path = str(frame.get("image_path", "")).strip()
    frame_id = str(frame.get("frame_id", "")).strip()
    if not image_path or not frame_id:
        return False

    target_id = tracking_state.get("latest_target_id")
    if target_id in (None, "", []):
        return False

    bbox = detection.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return False

    persisted_current_frame_path = resolve_project_path(image_path)
    if not persisted_current_frame_path.exists():
        return False

    session_dirs = ensure_session_dirs(artifacts_root, session_id)
    crop_path = session_dirs["crops_dir"] / f"{persisted_current_frame_path.stem}_id_{target_id}.jpg"
    save_target_crop(persisted_current_frame_path, bbox, crop_path)
    current_frame_reference_path = persist_reference_frame(
        persisted_current_frame_path,
        session_dirs["frames_dir"] / f"{persisted_current_frame_path.stem}.jpg",
    )
    session = sessions.load(session_id)
    rewrite_output = execute_rewrite_memory_tool(
        session_file=Path(session.state_paths["session_path"]),
        arguments=build_rewrite_memory_input(
            behavior="track",
            crop_path=crop_path,
            frame_paths=rewrite_memory_frame_paths(
                behavior="track",
                current_frame_path=current_frame_reference_path,
            ),
            frame_id=frame_id,
            target_id=int(target_id),
            desired_reference_view=desired_reference_view_goal(
                state_root=sessions.state_root,
                session_id=session_id,
            ),
        ),
        env_file=env_file,
    )
    apply_tracking_rewrite_output(
        sessions=sessions,
        session_id=session_id,
        rewrite_output=rewrite_output,
    )
    return True


def recover_latest_tracking_rewrite_if_stale(*, sessions: AgentSessionStore, session_id: str) -> None:
    _ = sessions
    _ = session_id
    return None


def _build_init_trigger(*, request_id: str, text: str, frame_id: str | None) -> TrackingTrigger:
    return TrackingTrigger(
        type=TRIGGER_CHAT_INIT,
        cause="new_user_target",
        frame_id=frame_id,
        request_id=request_id,
        requested_text=str(text),
        source="tracking_init_skill",
    )


def _build_followup_trigger(*, session, request_id: str, text: str) -> TrackingTrigger:
    latest_frame = latest_tracking_frame(session)
    frame_id = str(latest_frame.get("frame_id", "")).strip() or None
    bound_request_id = str(session.session.get("latest_request_id", "") or "").strip() or request_id
    return TrackingTrigger(
        type=TRIGGER_EVENT_REBIND,
        cause="direct_request",
        frame_id=frame_id,
        request_id=bound_request_id,
        requested_text=str(text),
        source="tracking_direct",
    )


def _should_treat_as_init_followup(session) -> bool:
    state = normalize_tracking_state(session.capabilities.get(TRACKING_SKILL_NAME))
    return bool(state.pending_question) or state.latest_target_id is None


def _select_init_payload(
    *,
    session,
    request_id: str,
    text: str,
    env_file: Path,
    artifacts_root: Path,
) -> Dict[str, Any]:
    context = build_tracking_init_context(session, request_id=request_id)
    return execute_select_tool(
        tracking_context=context,
        behavior="init",
        arguments={"target_description": str(text)},
        env_file=env_file,
        artifacts_root=artifacts_root,
    )


def _rewrite_init_memory_sync(
    *,
    sessions: AgentSessionStore,
    session,
    session_id: str,
    select_output: Dict[str, Any],
    env_file: Path,
) -> Dict[str, Any]:
    rewrite_memory_input = dict(select_output.get("rewrite_memory_input") or {})
    if not rewrite_memory_input or not bool(select_output.get("found", False)):
        return select_output

    rewrite_output = execute_rewrite_memory_tool(
        session_file=Path(session.state_paths["session_path"]),
        arguments=rewrite_memory_input,
        env_file=env_file,
    )
    apply_tracking_rewrite_output(
        sessions=sessions,
        session_id=session_id,
        rewrite_output=rewrite_output,
    )

    updated_output = dict(select_output)
    updated_output.pop("rewrite_memory_input", None)
    return updated_output


def process_tracking_init_direct(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    device_id: str,
    text: str,
    request_id: str,
    env_file: Path,
    artifacts_root: Path,
    append_chat_request: bool = True,
    acquire_turn: bool = True,
    turn_owner_id: str | None = None,
    wait_for_turn: bool = True,
    turn_kind: str | None = None,
) -> Dict[str, Any]:
    resolved_turn_owner_id = str(
        turn_owner_id
        or os.environ.get("ROBOT_AGENT_TURN_OWNER_ID")
        or DEFAULT_PI_TURN_OWNER_ID
    ).strip()
    resolved_turn_kind = str(turn_kind or "pi:tracking-init").strip()
    if acquire_turn:
        acquired = sessions.acquire_turn(
            session_id=session_id,
            owner_id=resolved_turn_owner_id,
            turn_kind=resolved_turn_kind,
            request_id=request_id,
            device_id=device_id,
            wait=wait_for_turn,
        )
        if acquired is None:
            raise RuntimeError(f"Could not acquire runner turn lease for {resolved_turn_kind}.")
    try:
        if append_chat_request:
            sessions.append_chat_request(
                session_id=session_id,
                device_id=device_id,
                text=text,
                request_id=request_id,
            )
        session = sessions.load(session_id, device_id=device_id)
        trigger = _build_init_trigger(
            request_id=request_id,
            text=text,
            frame_id=str(latest_tracking_frame(session).get("frame_id", "")).strip() or None,
        )
        try:
            select_output = _select_init_payload(
                session=session,
                request_id=request_id,
                text=text,
                env_file=env_file,
                artifacts_root=artifacts_root,
            )
            select_output = _rewrite_init_memory_sync(
                sessions=sessions,
                session=session,
                session_id=session_id,
                select_output=select_output,
                env_file=env_file,
            )
        except Exception as exc:
            select_output = {
                "behavior": "init",
                "frame_id": trigger.frame_id,
                "target_id": None,
                "bounding_box_id": None,
                "found": False,
                "decision": "ask",
                "text": "当前无法确认目标，请补充描述。",
                "reason": f"Direct init turn failed.\n{exc}",
                "needs_clarification": True,
                "clarification_question": "当前无法确认目标，请补充描述。",
                "reject_reason": "",
                "target_description": str(text),
            }

        decision = decision_from_select_output(
            trigger=trigger,
            select_output=select_output,
            target_description=str(text),
        )
        return apply_tracking_decision(
            sessions=sessions,
            session_id=session_id,
            session=session,
            trigger=trigger,
            decision=decision,
            env_file=env_file,
        )
    finally:
        if acquire_turn:
            sessions.release_turn(
                session_id=session_id,
                owner_id=resolved_turn_owner_id,
                request_id=request_id,
                device_id=device_id,
            )


def process_tracking_request_direct(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    device_id: str,
    text: str,
    request_id: str,
    env_file: Path,
    artifacts_root: Path,
    excluded_track_ids: list[int] | None = None,
    append_chat_request: bool = True,
    acquire_turn: bool = True,
    turn_owner_id: str | None = None,
    wait_for_turn: bool = True,
    turn_kind: str | None = None,
) -> Dict[str, Any]:
    resolved_turn_owner_id = str(
        turn_owner_id
        or os.environ.get("ROBOT_AGENT_TURN_OWNER_ID")
        or (DEFAULT_PI_TURN_OWNER_ID if append_chat_request else DEFAULT_TRACKING_TURN_OWNER_ID)
    ).strip()
    resolved_turn_kind = str(
        turn_kind or ("pi:tracking-init-followup" if append_chat_request else "tracking-init-runtime")
    ).strip()
    if acquire_turn:
        acquired = sessions.acquire_turn(
            session_id=session_id,
            owner_id=resolved_turn_owner_id,
            turn_kind=resolved_turn_kind,
            request_id=request_id,
            device_id=device_id,
            wait=wait_for_turn,
        )
        if acquired is None:
            raise RuntimeError(f"Could not acquire runner turn lease for {resolved_turn_kind}.")
    try:
        if append_chat_request:
            sessions.append_chat_request(
                session_id=session_id,
                device_id=device_id,
                text=text,
                request_id=request_id,
            )
        session = sessions.load(session_id, device_id=device_id)
        if append_chat_request and _should_treat_as_init_followup(session):
            return process_tracking_init_direct(
                sessions=sessions,
                session_id=session_id,
                device_id=device_id,
                text=text,
                request_id=request_id,
                env_file=env_file,
                artifacts_root=artifacts_root,
                append_chat_request=False,
                acquire_turn=False,
                turn_owner_id=resolved_turn_owner_id,
                wait_for_turn=wait_for_turn,
                turn_kind="pi:tracking-init-followup",
            )

        trigger = _build_followup_trigger(session=session, request_id=request_id, text=text)
        return run_tracking_agent_turn(
            sessions=sessions,
            session_id=session_id,
            session=session,
            trigger=trigger,
            env_file=env_file,
            artifacts_root=artifacts_root,
            excluded_track_ids=excluded_track_ids,
        )
    finally:
        if acquire_turn:
            sessions.release_turn(
                session_id=session_id,
                owner_id=resolved_turn_owner_id,
                request_id=request_id,
                device_id=device_id,
            )
