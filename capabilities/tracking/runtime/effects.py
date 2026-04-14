from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from agent.state.session import AgentSession, AgentSessionStore
from capabilities.tracking.policy.rewrite_memory import execute_rewrite_memory_tool
from capabilities.tracking.runtime.context import (
    TRACKING_LIFECYCLE_BOUND,
    TRACKING_LIFECYCLE_SCHEDULED,
    TRACKING_LIFECYCLE_SEEKING,
    normalize_tracking_state,
)
from capabilities.tracking.runtime.types import (
    ACTION_ASK,
    ACTION_TRACK,
    ACTION_WAIT,
    TrackingDecision,
    TrackingTrigger,
)
from capabilities.tracking.state.memory import write_tracking_memory_snapshot

TRACKING_SKILL_NAME = "tracking-init"
PENDING_REWRITE_INPUT_KEY = "pending_rewrite_input"
PENDING_REWRITE_REQUEST_ID_KEY = "pending_rewrite_request_id"
PENDING_REWRITE_ENQUEUED_AT_KEY = "pending_rewrite_enqueued_at"
PENDING_REWRITE_ERROR_KEY = "pending_rewrite_error"
LAST_REWRITE_COMPLETED_AT_KEY = "last_rewrite_completed_at"
LAST_REWRITE_REQUEST_ID_KEY = "last_rewrite_request_id"


def _compact_response_payload(
    *,
    session_id: str,
    skill_name: str,
    session_result: Dict[str, Any],
    skill_state_patch: Optional[Dict[str, Any]],
    robot_response: Optional[Dict[str, Any]],
    tool: str,
    tool_output: Optional[Dict[str, Any]],
    rewrite_output: Optional[Dict[str, Any]],
    rewrite_memory_input: Optional[Dict[str, Any]],
    latest_result: Dict[str, Any] | None,
    session: Dict[str, Any],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "status": "processed",
        "skill_name": skill_name,
        "session_result": session_result,
        "tool": tool,
        "latest_result": latest_result,
        "session": session,
    }
    optional_fields = {
        "skill_state_patch": skill_state_patch,
        "robot_response": robot_response,
        "tool_output": tool_output,
        "rewrite_output": rewrite_output,
        "rewrite_memory_input": rewrite_memory_input,
    }
    for key, value in optional_fields.items():
        if isinstance(value, dict):
            if value:
                payload[key] = value
        elif value is not None:
            payload[key] = value
    return payload


def _dropped_tracking_payload(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    trigger: TrackingTrigger,
) -> Dict[str, Any]:
    session = sessions.load(session_id)
    return {
        "session_id": session_id,
        "status": "dropped",
        "skill_name": TRACKING_SKILL_NAME,
        "request_id": trigger.request_id,
        "latest_request_id": str(session.session.get("latest_request_id", "") or "").strip(),
        "reason": "stale_request",
        "latest_result": session.latest_result,
        "session": session.session,
    }


def decision_from_select_output(
    *,
    trigger: TrackingTrigger,
    select_output: Dict[str, Any],
    target_description: str = "",
) -> TrackingDecision:
    return TrackingDecision(
        action=str(select_output.get("decision", "")).strip(),
        frame_id=str(select_output.get("frame_id", "") or "").strip() or trigger.frame_id,
        target_id=select_output.get("target_id"),
        text=str(select_output.get("text", "")).strip(),
        reason=str(select_output.get("reason", "")).strip(),
        question=str(select_output.get("clarification_question", "") or "").strip() or None,
        reject_reason=str(select_output.get("reject_reason", "") or "").strip(),
        target_description=target_description or str(select_output.get("target_description", "")).strip(),
        candidate_checks=list(select_output.get("candidate_checks") or []),
        memory_effect={"rewrite_input": dict(select_output.get("rewrite_memory_input") or {})} if select_output.get("rewrite_memory_input") else None,
        tool_output=dict(select_output),
    )


def _behavior_for_trigger(trigger: TrackingTrigger) -> str:
    return "init" if trigger.type == "chat_init" else "track"


def _robot_response(decision: TrackingDecision) -> Dict[str, Any]:
    if decision.action == ACTION_ASK:
        return {
            "action": "ask",
            "question": decision.question or decision.text,
            "text": decision.text,
        }
    if decision.action == ACTION_WAIT:
        return {
            "action": "wait",
            "text": decision.text,
        }
    return {
        "action": "track",
        "target_id": decision.target_id,
        "text": decision.text,
    }


def _session_result(decision: TrackingDecision, trigger: TrackingTrigger, request_id: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "request_id": request_id,
        "function": "chat",
        "behavior": _behavior_for_trigger(trigger),
        "frame_id": decision.frame_id,
        "target_id": decision.target_id,
        "bounding_box_id": decision.target_id,
        "found": decision.action == ACTION_TRACK and decision.target_id not in (None, ""),
        "decision": decision.action,
        "text": decision.text,
    }
    if str(decision.reason or "").strip():
        result["reason"] = str(decision.reason).strip()
    if decision.reject_reason:
        result["reject_reason"] = decision.reject_reason
    if decision.action == ACTION_ASK and decision.question:
        result["needs_clarification"] = True
        result["clarification_question"] = decision.question
    return result


def _tracking_state_patch(
    *,
    previous_state,
    decision: TrackingDecision,
    trigger: TrackingTrigger,
) -> Dict[str, Any]:
    patch: Dict[str, Any] = {
        "last_reviewed_trigger": trigger.type,
        "last_reviewed_cause": trigger.cause,
    }
    if decision.frame_id:
        patch["last_completed_frame_id"] = decision.frame_id

    if trigger.type == "chat_init" and decision.target_description:
        patch["target_description"] = decision.target_description

    if decision.action == ACTION_ASK:
        if trigger.type == "chat_init":
            patch["latest_target_id"] = None
        patch["pending_question"] = decision.question or decision.text
        patch["lifecycle_status"] = TRACKING_LIFECYCLE_SEEKING
        return patch

    patch["pending_question"] = None
    if decision.action == ACTION_TRACK and decision.target_id is not None:
        patch["latest_target_id"] = int(decision.target_id)
        patch["lifecycle_status"] = (
            TRACKING_LIFECYCLE_SCHEDULED if trigger.type == "chat_init" else TRACKING_LIFECYCLE_BOUND
        )
        if trigger.type == "chat_init":
            patch["generation"] = int(previous_state.generation or 0) + 1
            patch["stop_reason"] = None
    else:
        if trigger.type == "chat_init":
            patch["latest_target_id"] = None
        patch["lifecycle_status"] = TRACKING_LIFECYCLE_SEEKING
    return patch


def _memory_rewrite_input(memory_effect: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    rewrite_input = None if not isinstance(memory_effect, dict) else dict(memory_effect.get("rewrite_input") or {})
    if not rewrite_input:
        return None
    return rewrite_input


def _queued_rewrite_patch(rewrite_input: Optional[Dict[str, Any]], *, request_id: str) -> Dict[str, Any]:
    if not isinstance(rewrite_input, dict) or not rewrite_input:
        return {
            PENDING_REWRITE_INPUT_KEY: None,
            PENDING_REWRITE_REQUEST_ID_KEY: None,
            PENDING_REWRITE_ENQUEUED_AT_KEY: None,
            PENDING_REWRITE_ERROR_KEY: None,
        }
    return {
        PENDING_REWRITE_INPUT_KEY: dict(rewrite_input),
        PENDING_REWRITE_REQUEST_ID_KEY: str(request_id).strip(),
        PENDING_REWRITE_ENQUEUED_AT_KEY: time.time(),
        PENDING_REWRITE_ERROR_KEY: None,
    }


def _clear_pending_rewrite_patch(*, request_id: str | None = None, error: str | None = None) -> Dict[str, Any]:
    patch: Dict[str, Any] = {
        PENDING_REWRITE_INPUT_KEY: None,
        PENDING_REWRITE_REQUEST_ID_KEY: None,
        PENDING_REWRITE_ENQUEUED_AT_KEY: None,
        PENDING_REWRITE_ERROR_KEY: str(error or "").strip() or None,
    }
    if request_id:
        patch[LAST_REWRITE_REQUEST_ID_KEY] = str(request_id).strip()
    if error in (None, ""):
        patch[LAST_REWRITE_COMPLETED_AT_KEY] = time.time()
    return patch


def pending_tracking_memory_rewrite(session: AgentSession) -> Optional[Dict[str, Any]]:
    tracking_state = dict(session.capabilities.get(TRACKING_SKILL_NAME) or {})
    rewrite_input = tracking_state.get(PENDING_REWRITE_INPUT_KEY)
    if not isinstance(rewrite_input, dict) or not rewrite_input:
        return None
    normalized = dict(rewrite_input)
    request_id = str(
        tracking_state.get(PENDING_REWRITE_REQUEST_ID_KEY)
        or normalized.get("request_id")
        or ""
    ).strip()
    if request_id:
        normalized["request_id"] = request_id
    return normalized


def drain_pending_tracking_memory_rewrite(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    env_file: Path,
) -> Dict[str, Any]:
    session = sessions.load(session_id)
    rewrite_input = pending_tracking_memory_rewrite(session)
    if rewrite_input is None:
        return {"status": "idle"}

    tracking_state = normalize_tracking_state(session.capabilities.get(TRACKING_SKILL_NAME))
    target_request_id = str(rewrite_input.get("request_id", "") or "").strip()
    current_request_id = str(session.session.get("latest_request_id", "") or "").strip()
    target_id = rewrite_input.get("target_id")

    if target_request_id and current_request_id and current_request_id != target_request_id:
        sessions.patch_skill_state(
            session_id,
            skill_name=TRACKING_SKILL_NAME,
            patch=_clear_pending_rewrite_patch(request_id=target_request_id, error="stale_request"),
        )
        return {"status": "dropped", "reason": "stale_request", "request_id": target_request_id}
    if target_id not in (None, "") and tracking_state.latest_target_id not in (None, ""):
        if int(target_id) != int(tracking_state.latest_target_id):
            sessions.patch_skill_state(
                session_id,
                skill_name=TRACKING_SKILL_NAME,
                patch=_clear_pending_rewrite_patch(request_id=target_request_id, error="stale_target"),
            )
            return {"status": "dropped", "reason": "stale_target", "request_id": target_request_id}

    try:
        rewrite_output = execute_rewrite_memory_tool(
            session_file=Path(session.state_paths["session_path"]),
            arguments=dict(rewrite_input),
            env_file=env_file,
        )
    except Exception as exc:
        sessions.patch_skill_state(
            session_id,
            skill_name=TRACKING_SKILL_NAME,
            patch=_clear_pending_rewrite_patch(request_id=target_request_id, error=f"rewrite_failed: {exc}"),
        )
        return {
            "status": "failed",
            "reason": "rewrite_failed",
            "request_id": target_request_id,
            "error": str(exc),
        }

    refreshed_session = sessions.load(session_id)
    refreshed_tracking_state = normalize_tracking_state(refreshed_session.capabilities.get(TRACKING_SKILL_NAME))
    refreshed_request_id = str(refreshed_session.session.get("latest_request_id", "") or "").strip()
    if target_request_id and refreshed_request_id and refreshed_request_id != target_request_id:
        sessions.patch_skill_state(
            session_id,
            skill_name=TRACKING_SKILL_NAME,
            patch=_clear_pending_rewrite_patch(request_id=target_request_id, error="stale_request"),
        )
        return {"status": "dropped", "reason": "stale_request", "request_id": target_request_id}
    if target_id not in (None, "") and refreshed_tracking_state.latest_target_id not in (None, ""):
        if int(target_id) != int(refreshed_tracking_state.latest_target_id):
            sessions.patch_skill_state(
                session_id,
                skill_name=TRACKING_SKILL_NAME,
                patch=_clear_pending_rewrite_patch(request_id=target_request_id, error="stale_target"),
            )
            return {"status": "dropped", "reason": "stale_target", "request_id": target_request_id}

    write_tracking_memory_snapshot(
        state_root=Path(refreshed_session.state_paths["state_root"]),
        session_id=refreshed_session.session_id,
        memory=rewrite_output["memory"],
        crop_path=rewrite_output.get("crop_path"),
        reference_view=rewrite_output.get("reference_view"),
        reset=str(rewrite_output.get("task", "")).strip() == "init",
    )
    sessions.patch_skill_state(
        session_id,
        skill_name=TRACKING_SKILL_NAME,
        patch=_clear_pending_rewrite_patch(request_id=target_request_id),
    )
    return {
        "status": "processed",
        "request_id": target_request_id,
        "rewrite_output": rewrite_output,
    }


def apply_tracking_decision(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    session: AgentSession,
    trigger: TrackingTrigger,
    decision: TrackingDecision,
    env_file: Path,
) -> Dict[str, Any]:
    previous_state = normalize_tracking_state(session.capabilities.get(TRACKING_SKILL_NAME))
    current_request_id = str(sessions.load(session_id).session.get("latest_request_id", "") or "").strip()
    if current_request_id and current_request_id != trigger.request_id:
        return _dropped_tracking_payload(
            sessions=sessions,
            session_id=session_id,
            trigger=trigger,
        )
    session_result = _session_result(decision, trigger, trigger.request_id)
    robot_response = _robot_response(decision)

    memory_effect = (
        None
        if not isinstance(decision.memory_effect, dict)
        else {
            **dict(decision.memory_effect),
            "rewrite_input": {
                **dict(decision.memory_effect.get("rewrite_input") or {}),
                "request_id": trigger.request_id,
            },
        }
    )
    rewrite_input = _memory_rewrite_input(memory_effect)

    sessions.apply_skill_result(session_id, {**session_result, "robot_response": dict(robot_response)})
    committed_session = sessions.load(session_id)
    committed_request_id = str((committed_session.latest_result or {}).get("request_id", "") or "").strip()
    if committed_request_id != trigger.request_id:
        return _dropped_tracking_payload(
            sessions=sessions,
            session_id=session_id,
            trigger=trigger,
        )
    skill_state_patch = _tracking_state_patch(
        previous_state=previous_state,
        decision=decision,
        trigger=trigger,
    )
    skill_state_patch.update(
        _queued_rewrite_patch(rewrite_input, request_id=str(session_result["request_id"]))
    )
    sessions.patch_skill_state(session_id, skill_name=TRACKING_SKILL_NAME, patch=skill_state_patch)

    final_session = sessions.load(session_id)
    return _compact_response_payload(
        session_id=session_id,
        skill_name=TRACKING_SKILL_NAME,
        session_result=session_result,
        skill_state_patch=skill_state_patch,
        robot_response=robot_response,
        tool=_behavior_for_trigger(trigger),
        tool_output=dict(decision.tool_output),
        rewrite_output=None,
        rewrite_memory_input=rewrite_input,
        latest_result=final_session.latest_result,
        session=final_session.session,
    )
