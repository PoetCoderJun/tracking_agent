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
from tracking_agent.pipeline import (
    build_query_batches,
    extract_video_to_frame_queue,
    write_query_plan,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build sampled frames and a query-plan scaffold for tracking runs."
    )
    parser.add_argument("--video", required=True, help="Input video path.")
    parser.add_argument(
        "--runtime-dir",
        required=True,
        help="Runtime output directory for frames and query plan.",
    )
    parser.add_argument(
        "--env-file",
        default=".ENV",
        help="Path to the .ENV file containing DashScope and runtime defaults.",
    )
    parser.add_argument("--sample-fps", type=float, default=None)
    parser.add_argument("--query-interval-seconds", type=int, default=None)
    parser.add_argument("--recent-frame-count", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings(Path(args.env_file))

    sample_fps = args.sample_fps if args.sample_fps is not None else settings.sample_fps
    query_interval_seconds = (
        args.query_interval_seconds
        if args.query_interval_seconds is not None
        else settings.query_interval_seconds
    )
    recent_frame_count = (
        args.recent_frame_count
        if args.recent_frame_count is not None
        else settings.recent_frame_count
    )

    runtime_dir = Path(args.runtime_dir)
    manifest = extract_video_to_frame_queue(
        video_path=Path(args.video),
        runtime_dir=runtime_dir,
        sample_fps=sample_fps,
    )
    batches = build_query_batches(
        frames=manifest.frames,
        query_interval_seconds=query_interval_seconds,
        recent_frame_count=recent_frame_count,
    )
    query_plan_path = write_query_plan(
        runtime_dir=runtime_dir,
        batches=batches,
        query_interval_seconds=query_interval_seconds,
        recent_frame_count=recent_frame_count,
    )

    print(
        json.dumps(
            {
                "dashscope_base_url": settings.base_url,
                "dashscope_model": settings.model,
                "frame_manifest": manifest.manifest_path,
                "query_plan.json": str(query_plan_path),
                "sample_fps": sample_fps,
                "query_interval_seconds": query_interval_seconds,
                "recent_frame_count": recent_frame_count,
                "batch_count": len(batches),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
