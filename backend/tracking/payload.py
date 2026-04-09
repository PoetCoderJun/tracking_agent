#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Dict, Optional

from backend.skill_payload import processed_skill_payload
from backend.tracking.context import (
    TRACKING_LIFECYCLE_BOUND,
    TRACKING_LIFECYCLE_INACTIVE,
    TRACKING_LIFECYCLE_SCHEDULED,
    TRACKING_LIFECYCLE_SEEKING,
)


def _optional_text(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _wait_feedback_text(select_output: Dict[str, Any]) -> str:
    text = str(select_output.get("text", "")).strip()
    reject_reason = _optional_text(select_output.get("reject_reason"))
    decision = _optional_text(select_output.get("decision"))
    if decision != "wait" or reject_reason is None:
        return text
    if reject_reason in text:
        return text
    if not text:
        return reject_reason
    return f"{text} 原因：{reject_reason}"


def _session_result(select_output: Dict[str, Any]) -> Dict[str, Any]:
    decision = _optional_text(select_output.get("decision"))
    result = {
        "behavior": str(select_output.get("behavior", "")).strip(),
        "frame_id": _optional_text(select_output.get("frame_id")),
        "target_id": select_output.get("target_id"),
        "bounding_box_id": select_output.get("bounding_box_id"),
        "found": bool(select_output.get("found", False)),
        "text": _wait_feedback_text(select_output),
        "reason": _optional_text(select_output.get("reason")),
    }
    if decision is not None:
        result["decision"] = decision
    reject_reason = _optional_text(select_output.get("reject_reason"))
    if reject_reason is not None:
        result["reject_reason"] = reject_reason
    clarification_question = _optional_text(select_output.get("clarification_question"))
    if clarification_question is not None:
        result["needs_clarification"] = bool(select_output.get("needs_clarification", False))
        result["clarification_question"] = clarification_question
    return result


def _skill_state_patch(select_output: Dict[str, Any]) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    target_description = _optional_text(select_output.get("target_description"))
    if target_description is not None:
        patch["target_description"] = target_description

    decision = _optional_text(select_output.get("decision"))
    clarification_question = _optional_text(select_output.get("clarification_question"))
    if decision == "ask" and clarification_question is not None and bool(select_output.get("needs_clarification", False)):
        patch["pending_question"] = clarification_question
        patch["lifecycle_status"] = TRACKING_LIFECYCLE_SEEKING
        return patch

    if not bool(select_output.get("found", False)):
        patch["pending_question"] = None
        patch["lifecycle_status"] = TRACKING_LIFECYCLE_SEEKING if decision == "wait" else TRACKING_LIFECYCLE_INACTIVE
        return patch

    target_id = select_output.get("target_id")
    if target_id not in (None, ""):
        patch["latest_target_id"] = int(target_id)
    patch["pending_question"] = None
    patch["lifecycle_status"] = (
        TRACKING_LIFECYCLE_SCHEDULED
        if str(select_output.get("behavior", "")).strip() == "init"
        else TRACKING_LIFECYCLE_BOUND
    )
    return patch


def _robot_response(select_output: Dict[str, Any]) -> Dict[str, Any]:
    text = _wait_feedback_text(select_output)
    decision = _optional_text(select_output.get("decision"))
    if decision == "ask":
        return {
            "action": "ask",
            "question": _optional_text(select_output.get("clarification_question")) or text,
            "text": text,
        }
    if decision == "wait":
        return {
            "action": "wait",
            "text": text,
        }
    return {
        "action": "track",
        "target_id": select_output.get("target_id"),
        "text": text,
    }


def build_tracking_turn_payload(select_output: Dict[str, Any]) -> Dict[str, Any]:
    tool = str(select_output.get("behavior", "")).strip()
    if tool not in {"init", "track"}:
        raise ValueError(f"Unsupported tracking tool: {tool}")

    return processed_skill_payload(
        skill_name="tracking",
        session_result=_session_result(select_output),
        skill_state_patch=_skill_state_patch(select_output),
        robot_response=_robot_response(select_output),
        tool=tool,
        tool_output=dict(select_output),
        rewrite_memory_input=(
            dict(select_output.get("rewrite_memory_input") or {})
            if bool(select_output.get("found", False))
            else None
        ),
        reason=_optional_text(select_output.get("reason")),
    )


def ensure_rewrite_paths_exist(payload: Dict[str, Any]) -> Dict[str, Any]:
    rewrite_memory_input = dict(payload.get("rewrite_memory_input") or {})
    if not rewrite_memory_input:
        return payload

    crop_path = _optional_text(rewrite_memory_input.get("crop_path"))
    if crop_path is None:
        payload["rewrite_memory_input"] = None
        return payload

    frame_paths = [
        str(path).strip()
        for path in list(rewrite_memory_input.get("frame_paths") or [])
        if str(path).strip()
    ]
    if not frame_paths:
        payload["rewrite_memory_input"] = None
        return payload

    rewrite_memory_input["frame_paths"] = frame_paths
    payload["rewrite_memory_input"] = rewrite_memory_input
    return payload
