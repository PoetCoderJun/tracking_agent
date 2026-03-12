from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def _load_query_plan(query_plan_path: Path) -> Dict[str, Any]:
    return json.loads(query_plan_path.read_text(encoding="utf-8"))


def run_query_plan_inference(
    query_plan_path: Path,
    target_description: str,
    output_path: Path,
    client,
    max_batches: Optional[int] = None,
) -> Path:
    query_plan = _load_query_plan(query_plan_path)
    batches: Sequence[Dict[str, Any]] = query_plan.get("batches", [])
    if max_batches is not None:
        batches = batches[:max_batches]

    results: List[Dict[str, Any]] = []
    for batch in batches:
        frame_paths = [Path(frame["path"]) for frame in batch["frames"]]
        result = client.locate_target(
            target_description=target_description,
            frame_paths=frame_paths,
        )
        results.append(
            {
                "batch_index": batch["batch_index"],
                "query_time_seconds": batch["query_time_seconds"],
                "frame_paths": [str(path) for path in frame_paths],
                "result": result,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "target_description": target_description,
                "query_plan_path": str(query_plan_path),
                "query_interval_seconds": query_plan["query_interval_seconds"],
                "recent_frame_count": query_plan["recent_frame_count"],
                "results": results,
            },
            indent=2,
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    return output_path
