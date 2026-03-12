from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def load_frame_manifest(manifest_path: Path) -> Dict[str, Any]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_query_plan(query_plan_path: Path) -> Dict[str, Any]:
    return json.loads(query_plan_path.read_text(encoding="utf-8"))


def get_query_batch(query_plan_path: Path, batch_index: int) -> Dict[str, Any]:
    query_plan = load_query_plan(query_plan_path)
    for batch in query_plan.get("batches", []):
        if int(batch["batch_index"]) == batch_index:
            return batch
    raise KeyError(f"Could not find batch_index={batch_index} in {query_plan_path}")


def batch_frame_paths(query_plan_path: Path, batch_index: int) -> List[Path]:
    batch = get_query_batch(query_plan_path, batch_index)
    return [Path(frame["path"]) for frame in batch.get("frames", [])]
