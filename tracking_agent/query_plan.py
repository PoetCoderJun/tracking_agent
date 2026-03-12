from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List

from tracking_agent.frame_queue import FrameRecord


@dataclass(frozen=True)
class QueryBatch:
    batch_index: int
    query_time_seconds: float
    frames: List[FrameRecord]


def build_query_batches(
    frames: List[FrameRecord],
    query_interval_seconds: int,
    recent_frame_count: int,
) -> List[QueryBatch]:
    if query_interval_seconds <= 0:
        raise ValueError("query_interval_seconds must be positive")
    if recent_frame_count <= 0:
        raise ValueError("recent_frame_count must be positive")
    if not frames:
        return []

    batches: List[QueryBatch] = [
        QueryBatch(
            batch_index=0,
            query_time_seconds=0.0,
            frames=[frames[0]],
        )
    ]
    next_query_time = float(query_interval_seconds)

    for index, frame in enumerate(frames):
        if index + 1 < recent_frame_count:
            continue

        while frame.timestamp_seconds >= next_query_time:
            window = frames[index - recent_frame_count + 1 : index + 1]
            if len(window) == recent_frame_count:
                batches.append(
                    QueryBatch(
                        batch_index=len(batches),
                        query_time_seconds=next_query_time,
                        frames=window,
                    )
                )
            next_query_time += query_interval_seconds

    return batches


def write_query_plan(
    runtime_dir: Path,
    batches: List[QueryBatch],
    query_interval_seconds: int,
    recent_frame_count: int,
) -> Path:
    queries_dir = runtime_dir / "queries"
    queries_dir.mkdir(parents=True, exist_ok=True)
    query_plan_path = queries_dir / "query_plan.json"
    payload = {
        "query_interval_seconds": query_interval_seconds,
        "recent_frame_count": recent_frame_count,
        "batches": [
            {
                "batch_index": batch.batch_index,
                "query_time_seconds": batch.query_time_seconds,
                "frames": [asdict(frame) for frame in batch.frames],
            }
            for batch in batches
        ],
    }
    query_plan_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return query_plan_path
