#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.history_queue import get_query_batch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read one batch from a query plan.")
    parser.add_argument("--query-plan", required=True, help="Path to query_plan.json")
    parser.add_argument("--batch-index", required=True, type=int, help="Batch index to inspect")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    batch = get_query_batch(Path(args.query_plan), args.batch_index)
    print(json.dumps(batch, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
