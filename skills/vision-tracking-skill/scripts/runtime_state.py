#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.core import RuntimeStateStore, SessionStore
from tracking_agent.pipeline import get_query_batch, load_query_plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect or update runtime batch state.")
    parser.add_argument("--sessions-root", required=True, help="Directory containing session folders")
    parser.add_argument("--session-id", required=True, help="Session identifier")
    parser.add_argument("--query-plan", required=True, help="Path to query_plan.json")
    parser.add_argument(
        "--action",
        choices=("show", "current-batch", "next-batch", "advance", "reuse"),
        default="show",
    )
    parser.add_argument("--batch-index", type=int, default=None)
    return parser.parse_args()


def _batch_summary(batch):
    return {
        "batch_index": batch["batch_index"],
        "query_time_seconds": batch["query_time_seconds"],
        "frame_count": len(batch.get("frames", [])),
    }


def main() -> int:
    args = parse_args()
    query_plan_path = Path(args.query_plan)
    query_plan = load_query_plan(query_plan_path)
    total_batches = len(query_plan.get("batches", []))
    if not total_batches:
        raise ValueError(f"Query plan has no batches: {query_plan_path}")

    store = SessionStore(Path(args.sessions_root))
    runtime = RuntimeStateStore(store=store, session_id=args.session_id)
    state = runtime.ensure(query_plan_path=query_plan_path, total_batches=total_batches)

    if args.action == "show":
        print(json.dumps({"runtime_state": asdict(state)}, ensure_ascii=False))
        return 0

    if args.action == "current-batch":
        batch_index = state.last_batch_index if state.last_batch_index is not None else 0
        batch = get_query_batch(query_plan_path, batch_index)
        print(
            json.dumps(
                {"runtime_state": asdict(state), "batch": _batch_summary(batch)},
                ensure_ascii=False,
            )
        )
        return 0

    if args.action == "next-batch":
        batch = (
            get_query_batch(query_plan_path, state.next_batch_index)
            if state.next_batch_index < state.total_batches
            else None
        )
        print(
            json.dumps(
                {
                    "runtime_state": asdict(state),
                    "batch": _batch_summary(batch) if batch else None,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.batch_index is None:
        raise ValueError("--batch-index is required for advance/reuse")

    update = runtime.advance if args.action == "advance" else runtime.reuse
    updated = update(
        query_plan_path=query_plan_path,
        total_batches=total_batches,
        batch_index=args.batch_index,
    )
    print(json.dumps({"runtime_state": asdict(updated)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
