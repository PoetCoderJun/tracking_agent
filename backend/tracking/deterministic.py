from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from backend.perception.service import LocalPerceptionService
from backend.project_paths import resolve_project_path
from backend.runtime_session import AgentSessionStore
from backend.tracking.context import build_tracking_context
from backend.tracking.memory import normalize_tracking_memory, tracking_memory_display_text
from backend.tracking.rewrite_memory import execute_rewrite_memory_tool
from backend.tracking.select import (
    build_rewrite_memory_input,
    ensure_session_dirs,
    persist_reference_frame,
    rewrite_memory_frame_paths,
    execute_select_tool,
)
from backend.tracking.crop import save_target_crop
from backend.tracking.payload import build_tracking_turn_payload, ensure_rewrite_paths_exist

TRACKING_SKILL_NAME = "tracking"


def tracking_missing_reference_views(tracking_state: Dict[str, Any]) -> list[str]:
    latest_memory = normalize_tracking_memory(tracking_state.get("latest_memory", {}))
    missing: list[str] = []
    if not str(tracking_state.get("latest_front_target_crop", "") or "").strip() or not str(latest_memory.get("front_view", "") or "").strip():
        missing.append("front")
    if not str(tracking_state.get("latest_back_target_crop", "") or "").strip() or not str(latest_memory.get("back_view", "") or "").strip():
        missing.append("back")
    return missing


def desired_reference_view_goal(tracking_state: Dict[str, Any]) -> str:
    missing_views = tracking_missing_reference_views(tracking_state)
    if missing_views == ["front"]:
        return "front"
    if missing_views == ["back"]:
        return "back"
    if missing_views:
        return "any"
    return ""


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


def _rewrite_output_for_tracking_init(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    rewrite_memory_input: Dict[str, Any] | None,
    env_file: Path,
) -> Optional[Dict[str, Any]]:
    if not isinstance(rewrite_memory_input, dict) or not rewrite_memory_input:
        return None
    if str(rewrite_memory_input.get("task", "")).strip() != "init":
        return None
    session = sessions.load(session_id)
    return execute_rewrite_memory_tool(
        session_file=Path(session.state_paths["session_path"]),
        arguments=dict(rewrite_memory_input),
        env_file=env_file,
    )


def _merge_tracking_init_memory_text(
    *,
    session_result: Dict[str, Any],
    robot_response: Optional[Dict[str, Any]],
    rewrite_output: Optional[Dict[str, Any]],
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    if not isinstance(rewrite_output, dict):
        return session_result, robot_response
    memory_text = tracking_memory_display_text(rewrite_output.get("memory", {})).strip()
    if not memory_text:
        return session_result, robot_response

    merged_session_result = dict(session_result)
    base_text = str(merged_session_result.get("text", "")).strip()
    merged_session_result["text"] = f"{base_text}\n{memory_text}".strip() if base_text else memory_text

    if not isinstance(robot_response, dict):
        return merged_session_result, robot_response

    merged_robot_response = dict(robot_response)
    base_robot_text = str(merged_robot_response.get("text", "")).strip()
    merged_robot_response["text"] = f"{base_robot_text}\n{memory_text}".strip() if base_robot_text else memory_text
    return merged_session_result, merged_robot_response


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
    robot_response = _as_optional_dict(pi_payload.get("robot_response"), "robot_response")

    if rewrite_output is None:
        rewrite_output = _rewrite_output_for_tracking_init(
            sessions=sessions,
            session_id=session_id,
            rewrite_memory_input=rewrite_memory_input,
            env_file=env_file,
        )
        if rewrite_output is not None:
            rewrite_memory_input = None

    session_result, robot_response = _merge_tracking_init_memory_text(
        session_result=session_result,
        robot_response=robot_response,
        rewrite_output=rewrite_output,
    )

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

    if rewrite_output:
        apply_tracking_rewrite_output(
            sessions=sessions,
            session_id=session_id,
            rewrite_output=rewrite_output,
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
        "robot_response": robot_response or session_result.get("robot_response"),
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


def tracking_rewrite_still_relevant(
    sessions: AgentSessionStore,
    *,
    session_id: str,
    target_id: int,
    confirmed_frame_path: str,
) -> bool:
    session = sessions.load(session_id)
    tracking_state = dict(session.skills.get(TRACKING_SKILL_NAME) or {})
    current_target_id = tracking_state.get("latest_target_id")
    if current_target_id in (None, "", []):
        return False
    current_frame_path = str(tracking_state.get("latest_confirmed_frame_path", "") or "").strip()
    try:
        return int(current_target_id) == int(target_id) and current_frame_path == confirmed_frame_path
    except (TypeError, ValueError):
        return False


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

    confirmed_frame_path = frame_paths[-1]
    target_id = int(rewrite_memory_input["target_id"])
    if not tracking_rewrite_still_relevant(
        sessions,
        session_id=session_id,
        target_id=target_id,
        confirmed_frame_path=confirmed_frame_path,
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
        confirmed_frame_path=confirmed_frame_path,
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
            desired_reference_view=desired_reference_view_goal(tracking_state),
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
    session = sessions.load(session_id)
    rewrite_output = execute_rewrite_memory_tool(
        session_file=Path(session.state_paths["session_path"]),
        arguments=build_rewrite_memory_input(
            behavior="track",
            crop_path=crop_path,
            frame_paths=rewrite_memory_frame_paths(
                behavior="track",
                current_frame_path=confirmed_frame_path,
                latest_confirmed_frame_path=tracking_state.get("latest_confirmed_frame_path"),
            ),
            frame_id=frame_id,
            target_id=int(target_id),
            desired_reference_view=desired_reference_view_goal(tracking_state),
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


def build_tracking_wait_payload(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    device_id: str,
    reason: str,
) -> Dict[str, Any]:
    session = sessions.load(session_id, device_id=device_id)
    latest_observation = LocalPerceptionService(sessions.state_root).latest_camera_observation()
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
