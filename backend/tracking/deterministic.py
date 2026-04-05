from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from agent.session_store import AgentSessionStore
from backend.perception.service import LocalPerceptionService
from backend.project_paths import resolve_project_path
from backend.tracking.context import build_tracking_context
from backend.tracking.select import (
    build_rewrite_memory_input,
    ensure_session_dirs,
    persist_reference_frame,
    rewrite_memory_frame_paths,
    execute_select_tool,
)
from backend.tracking.crop import save_target_crop
from backend.tracking.payload import build_tracking_turn_payload, ensure_rewrite_paths_exist

ROOT = Path(__file__).resolve().parents[2]
TRACKING_SKILL_NAME = "tracking"


def _rewrite_memory_paths(request: Dict[str, Any]) -> tuple[Optional[str], list[str]]:
    crop_path = None if request.get("crop_path") in (None, "") else str(request["crop_path"]).strip()
    frame_paths = [
        str(path).strip()
        for path in list(request.get("frame_paths") or [])
        if str(path).strip()
    ]
    return crop_path, frame_paths


def _as_optional_dict(value: Any, field_name: str) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object or null")
    return dict(value)


def _tracking_skill_state_patch(pi_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    skill_state_patch = _as_optional_dict(pi_payload.get("skill_state_patch"), "skill_state_patch")
    if skill_state_patch is None:
        return None
    nested = skill_state_patch.get(TRACKING_SKILL_NAME)
    if len(skill_state_patch) == 1 and isinstance(nested, dict):
        return dict(nested)
    return skill_state_patch


def apply_processed_tracking_payload(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    pi_payload: Dict[str, Any],
    env_file: Path,
) -> Dict[str, Any]:
    skill_name = str(pi_payload.get("skill_name", "")).strip()
    if skill_name != TRACKING_SKILL_NAME:
        raise ValueError(f"Processed tracking payload must use skill_name={TRACKING_SKILL_NAME!r}")

    tool_output = _as_optional_dict(pi_payload.get("tool_output"), "tool_output")
    rewrite_output = _as_optional_dict(pi_payload.get("rewrite_output"), "rewrite_output")
    rewrite_memory_input = _as_optional_dict(pi_payload.get("rewrite_memory_input"), "rewrite_memory_input")
    session_result = _as_optional_dict(pi_payload.get("session_result"), "session_result")
    if session_result is None:
        raise ValueError("Processed tracking payload is missing session_result")

    sessions.apply_skill_result(
        session_id,
        session_result,
    )

    latest_result_patch = _as_optional_dict(pi_payload.get("latest_result_patch"), "latest_result_patch")
    if latest_result_patch:
        sessions.patch_latest_result(
            session_id=session_id,
            patch=latest_result_patch,
            expected_request_id=session_result.get("request_id"),
            expected_frame_id=session_result.get("frame_id"),
        )

    user_preferences_patch = _as_optional_dict(pi_payload.get("user_preferences_patch"), "user_preferences_patch")
    if user_preferences_patch:
        sessions.patch_user_preferences(session_id, user_preferences_patch)

    environment_map_patch = _as_optional_dict(pi_payload.get("environment_map_patch"), "environment_map_patch")
    if environment_map_patch:
        sessions.patch_environment(session_id, environment_map_patch)

    perception_cache_patch = _as_optional_dict(pi_payload.get("perception_cache_patch"), "perception_cache_patch")
    if perception_cache_patch:
        sessions.patch_perception(session_id, perception_cache_patch)

    skill_state_patch = _tracking_skill_state_patch(pi_payload)
    if skill_state_patch:
        sessions.patch_skill_state(
            session_id,
            skill_name=TRACKING_SKILL_NAME,
            patch=skill_state_patch,
        )

    if rewrite_memory_input:
        schedule_tracking_memory_rewrite(
            sessions=sessions,
            session_id=session_id,
            rewrite_memory_input=rewrite_memory_input,
            env_file=env_file,
        )

    final_session = sessions.load(session_id)
    return {
        "session_id": session_id,
        "status": "processed",
        "skill_name": TRACKING_SKILL_NAME,
        "session_result": session_result,
        "latest_result_patch": latest_result_patch,
        "skill_state_patch": skill_state_patch,
        "user_preferences_patch": user_preferences_patch,
        "environment_map_patch": environment_map_patch,
        "perception_cache_patch": perception_cache_patch,
        "robot_response": pi_payload.get("robot_response") or session_result.get("robot_response"),
        "tool": pi_payload.get("tool"),
        "tool_output": tool_output,
        "rewrite_output": rewrite_output,
        "rewrite_memory_input": rewrite_memory_input,
        "latest_result": final_session.latest_result,
        "session": final_session.session,
    }


def apply_tracking_rewrite_output(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    rewrite_output: Dict[str, Any],
) -> None:
    patch: Dict[str, Any] = {"latest_memory": rewrite_output["memory"]}
    crop_path = None if rewrite_output.get("crop_path") in (None, "") else str(rewrite_output["crop_path"]).strip()
    reference_view = str(rewrite_output.get("reference_view", "")).strip()
    if crop_path and reference_view == "front":
        patch["latest_front_target_crop"] = crop_path
    elif crop_path and reference_view == "back":
        patch["latest_back_target_crop"] = crop_path
    sessions.patch_skill_state(
        session_id,
        skill_name=TRACKING_SKILL_NAME,
        patch=patch,
    )


def schedule_tracking_memory_rewrite(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    rewrite_memory_input: Dict[str, Any],
    env_file: Path,
) -> None:
    crop_path, frame_paths = _rewrite_memory_paths(rewrite_memory_input)
    if crop_path in (None, "") or not frame_paths:
        return

    session = sessions.load(session_id)
    command = [
        sys.executable,
        "-m",
        "backend.tracking.rewrite_worker",
        "--state-root",
        str(session.state_paths["state_root"]),
        "--session-id",
        session_id,
        "--session-file",
        str(session.state_paths["session_path"]),
        "--task",
        str(rewrite_memory_input["task"]),
        "--crop-path",
        crop_path,
        "--frame-id",
        str(rewrite_memory_input["frame_id"]),
        "--target-id",
        str(rewrite_memory_input["target_id"]),
        "--env-file",
        str(env_file),
    ]
    confirmation_reason = rewrite_memory_input.get("confirmation_reason")
    if confirmation_reason not in (None, ""):
        command.extend(["--confirmation-reason", confirmation_reason])
    candidate_checks = rewrite_memory_input.get("candidate_checks")
    if isinstance(candidate_checks, list) and candidate_checks:
        command.extend(["--candidate-checks-json", json.dumps(candidate_checks, ensure_ascii=False)])
    for frame_path in frame_paths:
        command.extend(["--frame-path", frame_path])

    try:
        subprocess.Popen(
            command,
            cwd=ROOT,
            start_new_session=True,
        )
    except Exception as exc:
        raise RuntimeError(f"failed to launch tracking rewrite worker: {exc}") from exc


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
    confirmed_frame_path = persist_reference_frame(
        persisted_current_frame_path,
        session_dirs["frames_dir"] / f"{persisted_current_frame_path.stem}.jpg",
    )
    sessions.patch_skill_state(
        session_id,
        skill_name=TRACKING_SKILL_NAME,
        patch={
            "latest_target_id": int(target_id),
            "latest_confirmed_frame_path": str(confirmed_frame_path),
            "latest_confirmed_bbox": [int(value) for value in bbox],
            "latest_target_crop": str(crop_path),
        },
    )
    schedule_tracking_memory_rewrite(
        sessions=sessions,
        session_id=session_id,
        rewrite_memory_input=build_rewrite_memory_input(
            behavior="track",
            crop_path=crop_path,
            frame_paths=rewrite_memory_frame_paths(
                behavior="track",
                current_frame_path=confirmed_frame_path,
                latest_confirmed_frame_path=tracking_state.get("latest_confirmed_frame_path"),
            ),
            frame_id=frame_id,
            target_id=int(target_id),
        ),
        env_file=env_file,
    )
    return True


def recover_latest_tracking_rewrite_if_stale(*, sessions: AgentSessionStore, session_id: str) -> None:
    _ = sessions
    _ = session_id
    return None


def build_tracking_wait_payload(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    device_id: str,
    reason: str,
) -> Dict[str, Any]:
    session = sessions.load(session_id, device_id=device_id)
    latest_observation = LocalPerceptionService(sessions.state_root).latest_camera_observation(session_id=session_id)
    latest_frame_id = None if latest_observation is None else (latest_observation.get("payload") or {}).get("frame_id")
    tracking_state = dict((session.skills.get(TRACKING_SKILL_NAME) or {}))
    target_id = tracking_state.get("latest_target_id")
    text = "当前不确定，保持等待。"
    return {
        "status": "processed",
        "skill_name": TRACKING_SKILL_NAME,
        "session_result": {
            "behavior": "track",
            "frame_id": latest_frame_id,
            "target_id": target_id,
            "bounding_box_id": target_id,
            "found": False,
            "decision": "wait",
            "text": text,
            "reason": reason,
        },
        "latest_result_patch": None,
        "skill_state_patch": {"pending_question": None},
        "user_preferences_patch": None,
        "environment_map_patch": None,
        "perception_cache_patch": None,
        "robot_response": {"action": "wait", "text": text},
        "tool": "track",
        "tool_output": {"behavior": "track", "decision": "wait", "text": text, "reason": reason},
        "rewrite_output": None,
        "rewrite_memory_input": None,
        "reason": reason,
    }


def process_tracking_init_direct(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    device_id: str,
    text: str,
    request_id: str,
    env_file: Path,
    artifacts_root: Path,
    apply_processed_payload: Callable[..., Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    sessions.append_chat_request(
        session_id=session_id,
        device_id=device_id,
        text=text,
        request_id=request_id,
    )
    session = sessions.load(session_id, device_id=device_id)
    tracking_context = build_tracking_context(
        session,
        request_id=request_id,
    )
    processed_payload = apply_processed_payload or (
        lambda *, session_id, pi_payload, env_file: apply_processed_tracking_payload(
            sessions=sessions,
            session_id=session_id,
            pi_payload=pi_payload,
            env_file=env_file,
        )
    )
    try:
        payload = ensure_rewrite_paths_exist(
            build_tracking_turn_payload(
                execute_select_tool(
                    tracking_context=tracking_context,
                    behavior="init",
                    arguments={"target_description": str(text)},
                    env_file=env_file,
                    artifacts_root=artifacts_root,
                )
            )
        )
    except Exception as exc:
        clarification = "当前无法确认目标，请补充描述。"
        return processed_payload(
            session_id=session_id,
            pi_payload={
                "status": "processed",
                "skill_name": TRACKING_SKILL_NAME,
                "session_result": {
                    "behavior": "init",
                    "frame_id": None,
                    "target_id": None,
                    "bounding_box_id": None,
                    "found": False,
                    "needs_clarification": True,
                    "clarification_question": clarification,
                    "text": clarification,
                    "reason": f"Direct init turn failed.\n{exc}",
                },
                "latest_result_patch": None,
                "skill_state_patch": {"pending_question": clarification},
                "user_preferences_patch": None,
                "environment_map_patch": None,
                "perception_cache_patch": None,
                "robot_response": {
                    "action": "ask",
                    "question": clarification,
                    "text": clarification,
                },
                "tool": "init",
                "tool_output": None,
                "rewrite_output": None,
                "rewrite_memory_input": None,
                "reason": f"Direct init turn failed.\n{exc}",
            },
            env_file=env_file,
        )
    return processed_payload(session_id=session_id, pi_payload=payload, env_file=env_file)


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
    apply_processed_payload: Callable[..., Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    if append_chat_request:
        sessions.append_chat_request(
            session_id=session_id,
            device_id=device_id,
            text=text,
            request_id=request_id,
        )
    session = sessions.load(session_id, device_id=device_id)
    tracking_context = build_tracking_context(
        session,
        request_id=request_id,
        excluded_track_ids=excluded_track_ids,
    )
    processed_payload = apply_processed_payload or (
        lambda *, session_id, pi_payload, env_file: apply_processed_tracking_payload(
            sessions=sessions,
            session_id=session_id,
            pi_payload=pi_payload,
            env_file=env_file,
        )
    )
    try:
        payload = ensure_rewrite_paths_exist(
            build_tracking_turn_payload(
                execute_select_tool(
                    tracking_context=tracking_context,
                    behavior="track",
                    arguments={"user_text": str(text)},
                    env_file=env_file,
                    artifacts_root=artifacts_root,
                )
            )
        )
    except Exception as exc:
        return processed_payload(
            session_id=session_id,
            pi_payload=build_tracking_wait_payload(
                sessions=sessions,
                session_id=session_id,
                device_id=device_id,
                reason=f"Direct tracking turn failed.\n{exc}",
            ),
            env_file=env_file,
        )
    return processed_payload(session_id=session_id, pi_payload=payload, env_file=env_file)
