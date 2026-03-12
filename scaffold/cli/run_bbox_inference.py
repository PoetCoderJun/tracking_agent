#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.config import load_settings
from tracking_agent.dashscope_client import DashScopeVisionClient, build_locate_request_payload
from tracking_agent.inference_runner import run_query_plan_inference


class DryRunVisionClient:
    def __init__(self, model: str):
        self._model = model

    def locate_target(self, target_description: str, frame_paths):
        payload = build_locate_request_payload(
            model=self._model,
            target_description=target_description,
            frame_paths=frame_paths,
        )
        return {
            "found": False,
            "bbox": None,
            "confidence": 0.0,
            "reason": "dry-run only; request payload prepared but not sent",
            "request_preview": payload,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run DashScope vision bbox inference over a query plan."
    )
    parser.add_argument("--query-plan", required=True, help="Path to query_plan.json")
    parser.add_argument(
        "--target-description",
        required=True,
        help="Natural-language description of the target person.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path for bbox results JSON.",
    )
    parser.add_argument(
        "--env-file",
        default=".ENV",
        help="Path to the .ENV file containing DashScope settings.",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=None,
        help="Limit how many query batches to process.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build requests and write previews without calling DashScope.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings(Path(args.env_file))
    query_plan_path = Path(args.query_plan)
    output_path = (
        Path(args.output)
        if args.output
        else query_plan_path.parent / "bbox_results.json"
    )

    client = (
        DryRunVisionClient(settings.model)
        if args.dry_run
        else DashScopeVisionClient(settings)
    )
    results_path = run_query_plan_inference(
        query_plan_path=query_plan_path,
        target_description=args.target_description,
        output_path=output_path,
        client=client,
        max_batches=args.max_batches,
    )

    print(
        json.dumps(
            {
                "query_plan": str(query_plan_path),
                "results_path": str(results_path),
                "model": settings.model,
                "dry_run": args.dry_run,
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
