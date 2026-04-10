from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


TRIGGER_CHAT_INIT = "chat_init"
TRIGGER_CADENCE_REVIEW = "cadence_review"
TRIGGER_EVENT_REBIND = "event_rebind"

ACTION_TRACK = "track"
ACTION_WAIT = "wait"
ACTION_ASK = "ask"


@dataclass(frozen=True)
class TrackingTrigger:
    type: str
    cause: str
    frame_id: Optional[str]
    request_id: str
    requested_text: str = ""
    source: str = ""


@dataclass(frozen=True)
class TrackingState:
    target_description: str
    latest_target_id: int | None
    pending_question: str
    lifecycle_status: str
    generation: int
    next_tracking_turn_at: float | None
    last_completed_frame_id: str
    last_reviewed_trigger: str
    last_reviewed_cause: str
    stop_reason: str


@dataclass(frozen=True)
class TrackingObservation:
    session_id: str
    trigger: TrackingTrigger
    state: TrackingState
    memory: Dict[str, Any]
    latest_frame: Dict[str, Any]
    recent_frames: List[Dict[str, Any]]
    front_crop_path: Optional[str] = None
    back_crop_path: Optional[str] = None


@dataclass(frozen=True)
class TrackingDecision:
    action: str
    frame_id: Optional[str]
    target_id: int | None
    text: str
    reason: str
    question: Optional[str] = None
    reject_reason: str = ""
    target_description: str = ""
    candidate_checks: List[Dict[str, Any]] = field(default_factory=list)
    memory_effect: Optional[Dict[str, Any]] = None
    tool_output: Dict[str, Any] = field(default_factory=dict)
