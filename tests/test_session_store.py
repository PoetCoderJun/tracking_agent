from __future__ import annotations

from pathlib import Path

from tracking_agent.core import SessionStore


def test_session_store_focuses_on_memory_and_visualization_artifacts(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create_or_reset_session(
        session_id="demo",
        target_description="黑色衣服的人",
        initial_memory="黑衣、短发。",
    )

    assert session.latest_visualization_path is None
    assert Path(session.memory_path).exists()

    updated = store.set_latest_visualization_path(
        "demo",
        tmp_path / "sessions" / "demo" / "bbox_visualizations" / "step_0000.jpg",
    )

    assert updated.latest_visualization_path.endswith("step_0000.jpg")
