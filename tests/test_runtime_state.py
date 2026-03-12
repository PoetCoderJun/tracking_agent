from __future__ import annotations

import json
from pathlib import Path

from tracking_agent.core import RuntimeStateStore, SessionStore
from tracking_agent.pipeline import get_query_batch


def _write_query_plan(tmp_path: Path) -> Path:
    query_plan_path = tmp_path / "query_plan.json"
    query_plan_path.write_text(
        json.dumps(
            {
                "query_interval_seconds": 5,
                "recent_frame_count": 4,
                "batches": [
                    {
                        "batch_index": 0,
                        "query_time_seconds": 0.0,
                        "frames": [],
                    },
                    {
                        "batch_index": 1,
                        "query_time_seconds": 5.0,
                        "frames": [],
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return query_plan_path


def test_runtime_state_store_tracks_current_and_next_batches(tmp_path: Path) -> None:
    query_plan_path = _write_query_plan(tmp_path)
    store = SessionStore(tmp_path / "sessions")
    runtime = RuntimeStateStore(store=store, session_id="demo")

    state = runtime.ensure(query_plan_path=query_plan_path, total_batches=2)
    assert state.next_batch_index == 0
    assert state.last_batch_index is None

    batch = get_query_batch(query_plan_path, state.next_batch_index)
    assert batch["batch_index"] == 0

    state = runtime.reuse(query_plan_path=query_plan_path, total_batches=2, batch_index=0)
    assert state.next_batch_index == 1
    assert state.last_batch_index == 0

    state = runtime.advance(query_plan_path=query_plan_path, total_batches=2, batch_index=1)
    assert state.next_batch_index == 2
    assert state.last_batch_index == 1

    persisted = runtime.load()
    assert persisted.next_batch_index == 2
    assert persisted.last_batch_index == 1
