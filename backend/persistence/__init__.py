"""Persistence adapters for agent state and artifacts."""

from backend.persistence.active_session import (
    ActiveSessionRecord,
    ActiveSessionStore,
    resolve_session_id,
)
from backend.persistence.live_session_store import BackendDetection, BackendFrame, BackendSession, BackendStore

LiveDetection = BackendDetection
LiveFrame = BackendFrame
LiveSession = BackendSession
LiveSessionStore = BackendStore

__all__ = [
    "BackendDetection",
    "BackendFrame",
    "BackendSession",
    "BackendStore",
    "ActiveSessionRecord",
    "ActiveSessionStore",
    "LiveDetection",
    "LiveFrame",
    "LiveSession",
    "LiveSessionStore",
    "resolve_session_id",
]
