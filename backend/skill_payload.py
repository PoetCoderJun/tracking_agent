from __future__ import annotations

from typing import Any, Dict, Optional


def _optional_text(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _copy_optional_dict(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    copied = dict(value)
    return copied or None


def reply_robot_response(text: str) -> Dict[str, Any]:
    return {
        "action": "reply",
        "text": str(text).strip(),
    }


def reply_session_result(
    text: str,
    *,
    summary: Optional[str] = None,
    robot_response: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "behavior": "reply",
        "text": str(text).strip(),
    }
    cleaned_summary = None if summary in (None, "") else str(summary).strip()
    if cleaned_summary:
        result["summary"] = cleaned_summary
    response_payload = robot_response or reply_robot_response(result["text"])
    if response_payload:
        result["robot_response"] = dict(response_payload)
    return result


def processed_skill_payload(
    *,
    skill_name: str,
    session_result: Dict[str, Any],
    tool: str,
    tool_output: Optional[Dict[str, Any]] = None,
    latest_result_patch: Optional[Dict[str, Any]] = None,
    skill_state_patch: Optional[Dict[str, Any]] = None,
    user_preferences_patch: Optional[Dict[str, Any]] = None,
    environment_map_patch: Optional[Dict[str, Any]] = None,
    perception_cache_patch: Optional[Dict[str, Any]] = None,
    rewrite_output: Optional[Dict[str, Any]] = None,
    rewrite_memory_input: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    robot_response: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": "processed",
        "skill_name": str(skill_name).strip(),
        "session_result": dict(session_result),
        "tool": str(tool).strip(),
    }
    optional_patches = {
        "latest_result_patch": _copy_optional_dict(latest_result_patch),
        "skill_state_patch": _copy_optional_dict(skill_state_patch),
        "user_preferences_patch": _copy_optional_dict(user_preferences_patch),
        "environment_map_patch": _copy_optional_dict(environment_map_patch),
        "perception_cache_patch": _copy_optional_dict(perception_cache_patch),
        "tool_output": _copy_optional_dict(tool_output),
        "rewrite_output": _copy_optional_dict(rewrite_output),
        "rewrite_memory_input": _copy_optional_dict(rewrite_memory_input),
        "robot_response": _copy_optional_dict(robot_response),
    }
    for key, value in optional_patches.items():
        if value is not None:
            payload[key] = value

    cleaned_reason = _optional_text(reason)
    if cleaned_reason is not None:
        payload["reason"] = cleaned_reason
    return payload
