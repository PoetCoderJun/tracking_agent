from __future__ import annotations

from pathlib import Path

from agent import AgentSessionStore


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


def test_agent_session_store_updates_skill_and_perception_state(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "state")

    store.patch_perception("sess_001", {"vision": {"latest_frame_id": "frame_000001"}})
    updated = store.patch_skill_state(
        "sess_001",
        skill_name="tracking",
        patch={"last_tool": "track"},
    )

    assert updated.perception_cache["vision"]["latest_frame_id"] == "frame_000001"
    assert updated.skill_cache["tracking"]["last_tool"] == "track"


def test_agent_session_store_reset_clears_all_sections(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "state")
    store.patch_user_preferences("sess_001", {"language": "zh"})
    store.patch_environment("sess_001", {"dock": {"x": 1}})
    store.patch_perception("sess_001", {"vision": {"latest_frame_id": "frame_000001"}})
    store.patch_skill_state("sess_001", skill_name="tracking", patch={"latest_target_id": 7})

    reset = store.start_fresh_session("sess_001")

    assert reset.session_id == "sess_001"
    assert reset.user_preferences == {}
    assert reset.environment_map == {}
    assert reset.perception_cache == {}
    assert reset.skill_cache == {}
