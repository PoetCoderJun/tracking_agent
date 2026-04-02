from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.agent.session import AgentSession

ROUTE_DIALOGUE_LIMIT = 6


def _normalized_dialogue(history: Any, *, limit: int) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for entry in list(history or [])[-limit:]:
        if not isinstance(entry, dict):
            continue
        normalized.append(
            {
                "role": str(entry.get("role", "")).strip(),
                "text": str(entry.get("text", "")).strip(),
                "timestamp": str(entry.get("timestamp", "")).strip(),
            }
        )
    return normalized


def _latest_user_text(session_payload: Dict[str, Any]) -> str:
    for entry in reversed(list(session_payload.get("conversation_history") or [])):
        if str(entry.get("role", "")).strip() != "user":
            continue
        text = str(entry.get("text", "")).strip()
        if text:
            return text
    return ""


def build_route_context(
    session: AgentSession,
    *,
    request_id: str,
    enabled_skill_names: List[str],
    latest_frame: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    latest_result = dict(session.session.get("latest_result") or {})
    return {
        "session_id": session.session_id,
        "request_id": request_id,
        "enabled_skills": list(enabled_skill_names),
        "latest_user_text": _latest_user_text(session.session),
        "recent_dialogue": _normalized_dialogue(
            session.session.get("conversation_history"),
            limit=ROUTE_DIALOGUE_LIMIT,
        ),
        "latest_frame": None
        if latest_frame is None
        else {
            "frame_id": latest_frame["frame_id"],
            "timestamp_ms": latest_frame["timestamp_ms"],
            "detection_count": len(latest_frame["detections"]),
        },
        "latest_result": {
            "behavior": latest_result.get("behavior"),
            "frame_id": latest_result.get("frame_id"),
            "target_id": latest_result.get("target_id"),
            "found": latest_result.get("found"),
            "decision": latest_result.get("decision"),
            "text": str(latest_result.get("text", "")).strip(),
            "needs_clarification": latest_result.get("needs_clarification"),
            "clarification_question": latest_result.get("clarification_question"),
        }
        if latest_result
        else None,
    }
