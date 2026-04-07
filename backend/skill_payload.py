from __future__ import annotations

from typing import Any, Dict, Optional


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
    return {
        "status": "processed",
        "skill_name": str(skill_name).strip(),
        "session_result": dict(session_result),
        "latest_result_patch": None if latest_result_patch is None else dict(latest_result_patch),
        "skill_state_patch": None if skill_state_patch is None else dict(skill_state_patch),
        "user_preferences_patch": None if user_preferences_patch is None else dict(user_preferences_patch),
        "environment_map_patch": None if environment_map_patch is None else dict(environment_map_patch),
        "perception_cache_patch": None if perception_cache_patch is None else dict(perception_cache_patch),
        "robot_response": robot_response
        if robot_response is not None
        else dict(session_result.get("robot_response") or {}),
        "tool": str(tool).strip(),
        "tool_output": None if tool_output is None else dict(tool_output),
        "rewrite_output": None if rewrite_output is None else dict(rewrite_output),
        "rewrite_memory_input": None if rewrite_memory_input is None else dict(rewrite_memory_input),
        "reason": None if reason in (None, "") else str(reason).strip(),
    }
