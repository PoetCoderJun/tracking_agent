from __future__ import annotations

from pathlib import Path

from backend.agent import AgentMemoryStore


def test_agent_memory_store_merges_preferences_and_environment_map(tmp_path: Path) -> None:
    store = AgentMemoryStore(tmp_path / "state", "sess_001")

    store.update_user_preferences(
        {
            "language": "zh",
            "tracking": {"confirm_before_switch": True},
        }
    )
    updated = store.update_environment_map(
        {
            "rooms": {"kitchen": {"visited": True}},
            "dock": {"x": 1, "y": 2},
        }
    )

    assert updated.user_preferences["language"] == "zh"
    assert updated.user_preferences["tracking"]["confirm_before_switch"] is True
    assert updated.environment_map["rooms"]["kitchen"]["visited"] is True
    assert updated.environment_map["dock"] == {"x": 1, "y": 2}


def test_agent_memory_store_updates_skill_and_perception_cache(tmp_path: Path) -> None:
    store = AgentMemoryStore(tmp_path / "state", "sess_001")

    store.update_perception_cache({"vision": {"latest_frame_id": "frame_000001"}})
    updated = store.update_skill_cache(
        "tracking",
        {"last_tool": "track"},
    )

    assert updated.perception_cache["vision"]["latest_frame_id"] == "frame_000001"
    assert updated.skill_cache["tracking"]["last_tool"] == "track"


def test_agent_memory_store_reset_clears_all_sections(tmp_path: Path) -> None:
    store = AgentMemoryStore(tmp_path / "state", "sess_001")
    store.update_user_preferences({"language": "zh"})
    store.update_environment_map({"dock": {"x": 1}})
    store.update_perception_cache({"vision": {"latest_frame_id": "frame_000001"}})
    store.update_skill_cache("tracking", {"latest_target_id": 7})

    reset = store.reset()

    assert reset.session_id == "sess_001"
    assert reset.user_preferences == {}
    assert reset.environment_map == {}
    assert reset.perception_cache == {}
    assert reset.skill_cache == {}
