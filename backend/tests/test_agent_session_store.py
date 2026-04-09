from __future__ import annotations

from pathlib import Path

from backend.runtime_session import AgentSessionStore


def test_agent_session_store_merges_preferences_and_environment(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "state")

    store.patch_user_preferences(
        "sess_001",
        {
            "language": "zh",
            "tracking": {"confirm_before_switch": True},
        }
    )
    updated = store.patch_environment(
        "sess_001",
        {
            "rooms": {"kitchen": {"visited": True}},
            "dock": {"x": 1, "y": 2},
        }
    )

    assert updated.user_preferences["language"] == "zh"
    assert updated.user_preferences["tracking"]["confirm_before_switch"] is True
    assert updated.environment_map["rooms"]["kitchen"]["visited"] is True
    assert updated.environment_map["dock"] == {"x": 1, "y": 2}


def test_agent_session_store_keeps_perception_out_of_session_state(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "state")

    updated = store.patch_skill_state(
        "sess_001",
        skill_name="tracking",
        patch={"last_tool": "track"},
    )

    assert "memory" not in (updated.session.get("state") or {})
    assert updated.capabilities["tracking"]["last_tool"] == "track"


def test_agent_session_store_reset_clears_all_sections(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "state")
    store.patch_user_preferences("sess_001", {"language": "zh"})
    store.patch_environment("sess_001", {"dock": {"x": 1}})
    store.patch_skill_state("sess_001", skill_name="tracking", patch={"latest_target_id": 7})

    reset = store.start_fresh_session("sess_001")

    assert reset.session_id == "sess_001"
    assert reset.user_preferences == {}
    assert reset.environment_map == {}
    assert "memory" not in (reset.session.get("state") or {})
    assert reset.capabilities == {}


def test_agent_session_store_round_trips_runner_state_and_turn_lease(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "state")
    store.start_fresh_session("sess_001", device_id="robot_01")

    store.patch_runner_state(
        "sess_001",
        {
            "owner_id": "e-agent:sess_001",
            "turn_in_flight": False,
        },
    )
    acquired = store.acquire_turn(
        session_id="sess_001",
        owner_id="pi",
        turn_kind="pi:tracking-init",
        request_id="req_001",
        wait=False,
    )
    assert acquired is not None

    released = store.release_turn(
        session_id="sess_001",
        owner_id="pi",
        request_id="req_001",
    )
    assert released.runner_state["turn_in_flight"] is False
    assert released.runner_state["owner_id"] == ""
    assert released.runner_state["turn_request_id"] is None
