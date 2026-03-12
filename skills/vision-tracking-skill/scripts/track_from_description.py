#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.bbox_visualization import save_bbox_visualization
from tracking_agent.core import RuntimeStateStore, SessionStore
from tracking_agent.output_validator import denormalize_bbox_from_1000_scale
from tracking_agent.pipeline import get_query_batch, load_query_plan
from tracking_agent.target_crop import save_target_crop

SKILL_ROOT = Path(__file__).resolve().parents[1]
BUILD_QUERY_PLAN = SKILL_ROOT / "scripts" / "build_query_plan.py"
MAIN_AGENT = SKILL_ROOT / "scripts" / "main_agent_locate.py"
SUB_AGENT = SKILL_ROOT / "scripts" / "sub_agent_memory.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track a described target through a video.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--session-id", default="default")
    parser.add_argument("--target-description", required=True)
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--sample-fps", type=float, default=None)
    parser.add_argument("--query-interval-seconds", type=int, default=None)
    parser.add_argument("--recent-frame-count", type=int, default=None)
    parser.add_argument("--max-rounds", type=int, default=None)
    return parser.parse_args()


def _run_json(args: list[str]) -> Dict[str, Any]:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip())


def _run_command(args: list[str]) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def _normalized_to_pixel_bbox(bbox: list[int] | None, image_path: Path) -> list[int] | None:
    if bbox is None:
        return None
    with Image.open(image_path) as image:
        return denormalize_bbox_from_1000_scale(bbox, image.size)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _status_for_result(result: Dict[str, Any], has_bbox: bool) -> str:
    if has_bbox:
        return "tracked"
    if result.get("needs_clarification"):
        return "clarifying"
    return "missing"


def main() -> int:
    args = parse_args()
    log_dir = Path(args.log_dir)
    runtime_dir = log_dir / "runtime"
    sessions_root = log_dir / "sessions"
    session_dir = sessions_root / args.session_id
    rounds_dir = session_dir / "rounds"
    raw_dir = session_dir / "raw"
    bbox_dir = session_dir / "bbox_visualizations"
    crop_dir = session_dir / "reference_crops"
    summary_path = log_dir / "live_session_summary.json"
    query_plan_path = runtime_dir / "queries" / "query_plan.json"

    for path in (rounds_dir, raw_dir, bbox_dir, crop_dir):
        path.mkdir(parents=True, exist_ok=True)

    build_args = [
        sys.executable,
        str(BUILD_QUERY_PLAN),
        "--video",
        args.video,
        "--runtime-dir",
        str(runtime_dir),
        "--env-file",
        args.env_file,
    ]
    if args.sample_fps is not None:
        build_args.extend(["--sample-fps", str(args.sample_fps)])
    if args.query_interval_seconds is not None:
        build_args.extend(["--query-interval-seconds", str(args.query_interval_seconds)])
    if args.recent_frame_count is not None:
        build_args.extend(["--recent-frame-count", str(args.recent_frame_count)])
    _run_command(build_args)

    query_plan = load_query_plan(query_plan_path)
    store = SessionStore(sessions_root)
    runtime = RuntimeStateStore(store, args.session_id)
    runtime.ensure(query_plan_path, len(query_plan["batches"]))

    summary: Dict[str, Any] = {
        "query_interval_seconds": query_plan["query_interval_seconds"],
        "recent_frame_count": query_plan["recent_frame_count"],
        "log_dir": str(log_dir),
        "session_dir": str(session_dir),
        "target_description": args.target_description,
        "rounds": [],
    }

    batch0 = get_query_batch(query_plan_path, 0)
    frame0 = Path(batch0["frames"][-1]["path"])
    init_main = _run_json(
        [
            sys.executable,
            str(MAIN_AGENT),
            "--task",
            "init",
            "--env-file",
            args.env_file,
            "--target-description",
            args.target_description,
            "--image-path",
            str(frame0),
        ]
    )
    init_result = init_main["result"]
    init_pixel_bbox = _normalized_to_pixel_bbox(init_result.get("bbox"), frame0)
    init_vis_path = bbox_dir / "round_000_init.jpg"
    save_bbox_visualization(frame0, init_vis_path, init_pixel_bbox, "INIT")
    _write_json(raw_dir / "round_000_main_init.json", init_main)

    init_sub = None
    init_crop_path = None
    init_memory_path = None
    memory = ""
    if init_pixel_bbox is not None:
        init_crop_path = crop_dir / "round_000_crop.jpg"
        save_target_crop(frame0, init_pixel_bbox, init_crop_path)
        init_sub = _run_json(
            [
                sys.executable,
                str(SUB_AGENT),
                "--task",
                "init",
                "--env-file",
                args.env_file,
                "--image-path",
                str(init_crop_path),
                "--image-path",
                str(frame0),
            ]
        )
        memory = init_sub["memory"]
        init_memory_path = rounds_dir / "round_000_memory.md"
        init_memory_path.write_text(memory, encoding="utf-8")
        _write_json(raw_dir / "round_000_sub_init.json", init_sub)

    store.create_or_reset_session(args.session_id, args.target_description, memory)
    store.write_latest_result(args.session_id, init_result)
    store.set_latest_visualization_path(args.session_id, init_vis_path)
    if init_crop_path is not None:
        store.add_reference_crop(args.session_id, init_crop_path)
        store.set_latest_confirmed_frame_path(args.session_id, frame0)
    store.update_status(
        args.session_id,
        "initialized" if init_pixel_bbox is not None else _status_for_result(init_result, False),
        init_result.get("clarification_question"),
    )
    runtime.reuse(query_plan_path, len(query_plan["batches"]), 0)

    summary["rounds"].append(
        {
            "round_index": 0,
            "batch_index": 0,
            "frame_paths": [str(frame0)],
            "main_elapsed_seconds": init_main["elapsed_seconds"],
            "sub_elapsed_seconds": None if init_sub is None else init_sub["elapsed_seconds"],
            "normalized_bbox": init_result.get("bbox"),
            "pixel_bbox": init_pixel_bbox,
            "visualization_path": str(init_vis_path),
            "memory_path": None if init_memory_path is None else str(init_memory_path),
            "status": "initialized" if init_pixel_bbox is not None else _status_for_result(init_result, False),
        }
    )
    _write_json(summary_path, summary)
    print(json.dumps(summary["rounds"][-1], ensure_ascii=False), flush=True)

    track_batches = query_plan["batches"][1:]
    if args.max_rounds is not None:
        track_batches = track_batches[: args.max_rounds]

    for batch in track_batches:
        batch_index = int(batch["batch_index"])
        frame_paths = [Path(frame["path"]) for frame in batch["frames"]]
        latest_frame = frame_paths[-1]
        session = store.load_session(args.session_id)

        main_args = [
            sys.executable,
            str(MAIN_AGENT),
            "--task",
            "track",
            "--env-file",
            args.env_file,
            "--memory",
            store.read_memory(args.session_id),
        ]
        if session.latest_target_crop_path:
            main_args.extend(["--image-path", session.latest_target_crop_path])
        for frame_path in frame_paths:
            main_args.extend(["--image-path", str(frame_path)])
        track_main = _run_json(main_args)
        track_result = track_main["result"]
        track_pixel_bbox = _normalized_to_pixel_bbox(track_result.get("bbox"), latest_frame)
        vis_path = bbox_dir / f"round_{batch_index:03d}_track.jpg"
        save_bbox_visualization(latest_frame, vis_path, track_pixel_bbox, "TRACK")
        _write_json(raw_dir / f"round_{batch_index:03d}_main_track.json", track_main)

        track_sub = None
        memory_path = None
        if track_pixel_bbox is not None:
            crop_path = crop_dir / f"round_{batch_index:03d}_crop.jpg"
            save_target_crop(latest_frame, track_pixel_bbox, crop_path)
            track_sub = _run_json(
                [
                    sys.executable,
                    str(SUB_AGENT),
                    "--task",
                    "update",
                    "--env-file",
                    args.env_file,
                    "--image-path",
                    str(crop_path),
                    *[
                        item
                        for frame_path in frame_paths
                        for item in ("--image-path", str(frame_path))
                    ],
                ]
            )
            memory = track_sub["memory"]
            memory_path = rounds_dir / f"round_{batch_index:03d}_memory.md"
            memory_path.write_text(memory, encoding="utf-8")
            _write_json(raw_dir / f"round_{batch_index:03d}_sub_update.json", track_sub)
            store.write_memory(args.session_id, memory)
            store.add_reference_crop(args.session_id, crop_path)
            store.set_latest_confirmed_frame_path(args.session_id, latest_frame)

        status = _status_for_result(track_result, track_pixel_bbox is not None)
        store.write_latest_result(args.session_id, track_result)
        store.set_latest_visualization_path(args.session_id, vis_path)
        store.update_status(args.session_id, status, track_result.get("clarification_question"))
        runtime.advance(query_plan_path, len(query_plan["batches"]), batch_index)

        summary["rounds"].append(
            {
                "round_index": batch_index,
                "batch_index": batch_index,
                "frame_paths": [str(path) for path in frame_paths],
                "main_elapsed_seconds": track_main["elapsed_seconds"],
                "sub_elapsed_seconds": None if track_sub is None else track_sub["elapsed_seconds"],
                "normalized_bbox": track_result.get("bbox"),
                "pixel_bbox": track_pixel_bbox,
                "visualization_path": str(vis_path),
                "memory_path": None if memory_path is None else str(memory_path),
                "status": status,
            }
        )
        _write_json(summary_path, summary)
        print(json.dumps(summary["rounds"][-1], ensure_ascii=False), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
