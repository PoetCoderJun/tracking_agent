from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.state.backend import BackendStore
from agent.state.session import AgentSessionStore


def _write_session_payload(state_root: Path, session_id: str, payload: dict) -> Path:
    session_path = state_root / "sessions" / session_id / "session.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return session_path


def _session_payload(*, session_id: str = "sess_invalid", state: object | None = None, **extra: object) -> dict:
    payload = {
        "session_id": session_id,
        "device_id": "robot_01",
        "latest_request_id": None,
        "latest_request_function": None,
        "latest_result": None,
        "result_history": [],
        "conversation_history": [],
        "state": state,
        "created_at": "2026-04-14T00:00:00Z",
        "updated_at": "2026-04-14T00:00:00Z",
    }
    payload.update(extra)
    return payload


def test_backend_store_rejects_missing_state_object(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _write_session_payload(state_root, "sess_invalid", _session_payload(state=None))

    with pytest.raises(ValueError, match="Invalid session state"):
        BackendStore(state_root).load_session("sess_invalid")


def test_backend_store_rejects_missing_nested_sections(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _write_session_payload(
        state_root,
        "sess_invalid",
        _session_payload(
            state={
                "user_preferences": {},
                "environment": {},
                "runner": {},
            }
        ),
    )

    with pytest.raises(ValueError, match="state.capabilities"):
        BackendStore(state_root).load_session("sess_invalid")


def test_backend_store_rejects_non_object_nested_sections(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _write_session_payload(
        state_root,
        "sess_invalid",
        _session_payload(
            state={
                "user_preferences": {},
                "environment": {},
                "runner": [],
                "capabilities": {},
            }
        ),
    )

    with pytest.raises(ValueError, match="state.runner"):
        BackendStore(state_root).load_session("sess_invalid")


def test_backend_store_rejects_legacy_top_level_agent_state_keys(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    _write_session_payload(
        state_root,
        "sess_invalid",
        _session_payload(
            state={
                "user_preferences": {},
                "environment": {},
                "runner": {},
                "capabilities": {},
            },
            environment_map={},
        ),
    )

    with pytest.raises(ValueError, match="legacy top-level agent-state fields"):
        BackendStore(state_root).load_session("sess_invalid")


def test_agent_session_exposes_current_names_only(tmp_path: Path) -> None:
    sessions = AgentSessionStore(tmp_path / "state")
    session = sessions.start_fresh_session("sess_current", device_id="robot_01")

    assert session.environment == {}
    assert session.runner == {}
    assert session.capabilities == {}
    assert not hasattr(session, "environment_map")
    assert not hasattr(session, "runner_state")
