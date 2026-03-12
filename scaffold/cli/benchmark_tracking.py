#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.benchmark_tracking import (
    benchmark_tracking_run,
    summarize_benchmark_run,
    write_benchmark_result,
)
from tracking_agent.config import load_settings
from tracking_agent.dashscope_client import DashScopeVisionClient
from tracking_agent.dashscope_tracking_backend import DashScopeTrackingBackend
from tracking_agent.frame_queue import extract_video_to_frame_queue
from tracking_agent.query_plan import build_query_batches, write_query_plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark live Main-Agent/Sub-agent request durations over several tracking parameter combinations."
    )
    parser.add_argument("--video", required=True, help="Input video path")
    parser.add_argument(
        "--target-description",
        required=True,
        help="Natural-language description used to initialize the target",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for benchmark runtime artifacts and summary JSON files",
    )
    parser.add_argument(
        "--env-file",
        default=".ENV",
        help="Path to .ENV containing DashScope settings",
    )
    parser.add_argument(
        "--query-interval-seconds",
        default="5,8",
        help="Comma-separated query interval values to benchmark",
    )
    parser.add_argument(
        "--recent-frame-counts",
        default="2,4,6",
        help="Comma-separated recent-frame-count values to benchmark",
    )
    parser.add_argument(
        "--max-tracking-batches",
        type=int,
        default=1,
        help="How many tracking batches after init to benchmark per parameter combination",
    )
    parser.add_argument(
        "--sample-fps",
        type=float,
        default=1.0,
        help="Frame sampling fps for query-plan generation",
    )
    return parser.parse_args()


def _parse_int_list(raw_value: str):
    return [int(part.strip()) for part in raw_value.split(",") if part.strip()]


def main() -> int:
    args = parse_args()
    settings = load_settings(Path(args.env_file))
    backend = DashScopeTrackingBackend(
        DashScopeVisionClient(settings),
        main_model=settings.main_model,
        sub_model=settings.sub_model,
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_runtime_dir = output_dir / "base_frames"
    manifest = extract_video_to_frame_queue(
        video_path=Path(args.video),
        runtime_dir=base_runtime_dir,
        sample_fps=args.sample_fps,
    )

    summaries = []
    for recent_frame_count in _parse_int_list(args.recent_frame_counts):
        for query_interval_seconds in _parse_int_list(args.query_interval_seconds):
            combo_name = f"interval_{query_interval_seconds}_recent_{recent_frame_count}"
            combo_dir = output_dir / combo_name
            query_plan_path = write_query_plan(
                runtime_dir=combo_dir,
                batches=build_query_batches(
                    frames=manifest.frames,
                    query_interval_seconds=query_interval_seconds,
                    recent_frame_count=recent_frame_count,
                ),
                query_interval_seconds=query_interval_seconds,
                recent_frame_count=recent_frame_count,
            )
            print(
                json.dumps(
                    {
                        "event": "benchmark_start",
                        "query_interval_seconds": query_interval_seconds,
                        "recent_frame_count": recent_frame_count,
                        "query_plan_path": str(query_plan_path),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            run = benchmark_tracking_run(
                backend=backend,
                target_description=args.target_description,
                query_plan_path=query_plan_path,
                max_tracking_batches=args.max_tracking_batches,
            )
            result_path = write_benchmark_result(
                output_path=combo_dir / "benchmark_result.json",
                run=run,
            )
            summary = summarize_benchmark_run(run)
            summary["result_path"] = str(result_path)
            summaries.append(summary)
            print(json.dumps(summary, ensure_ascii=False), flush=True)

    summary_path = output_dir / "benchmark_summary.json"
    summary_path.write_text(
        json.dumps(summaries, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "event": "benchmark_complete",
                "summary_path": str(summary_path),
                "combination_count": len(summaries),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
