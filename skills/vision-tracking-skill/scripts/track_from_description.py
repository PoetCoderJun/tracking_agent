#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.bbox_visualization import save_bbox_visualization
from tracking_agent.core import RuntimeStateStore, SessionStore
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
    parser.add_argument("--detections-file", required=True)
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


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _status_for_result(result: Dict[str, Any], has_bbox: bool) -> str:
    if has_bbox:
        return "tracked"
    if result.get("needs_clarification"):
        return "clarifying"
    return "missing"


def _load_detection_index(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    index: Dict[str, List[Dict[str, Any]]] = {}

    def add_entry(key: str, detections: Any) -> None:
        if not isinstance(detections, list):
            raise ValueError(f"Detections for {key!r} must be a list")
        normalized: List[Dict[str, Any]] = []
        for detection in detections:
            if not isinstance(detection, dict):
                raise ValueError(f"Detection entries must be objects, got: {detection!r}")
            normalized.append(
                {
                    "track_id": int(detection["track_id"]),
                    "bbox": [int(value) for value in detection["bbox"]],
                    "score": float(detection.get("score", 1.0)),
                }
            )
        index[key] = normalized

    if isinstance(payload, dict) and isinstance(payload.get("frames"), list):
        for frame in payload["frames"]:
            if not isinstance(frame, dict):
                raise ValueError("frames entries must be objects")
            detections = frame.get("detections", [])
            for key in (
                frame.get("frame_id"),
                frame.get("image_path"),
                Path(str(frame["image_path"])).name if frame.get("image_path") else None,
                Path(str(frame["image_path"])).stem if frame.get("image_path") else None,
            ):
                if key:
                    add_entry(str(key), detections)
        return index

    if isinstance(payload, list):
        for frame in payload:
            if not isinstance(frame, dict) or "detections" not in frame:
                raise ValueError("List-form detections file must contain frame objects with detections")
            detections = frame.get("detections", [])
            for key in (
                frame.get("frame_id"),
                frame.get("image_path"),
                Path(str(frame["image_path"])).name if frame.get("image_path") else None,
                Path(str(frame["image_path"])).stem if frame.get("image_path") else None,
            ):
                if key:
                    add_entry(str(key), detections)
        return index

    if isinstance(payload, dict):
        for key, detections in payload.items():
            add_entry(str(key), detections)
        return index

    raise ValueError("Unsupported detections file format")


def _detections_for_frame(
    index: Dict[str, List[Dict[str, Any]]],
    frame_path: Path,
    frame_id: str,
) -> List[Dict[str, Any]]:
    lookup_keys = (frame_id, str(frame_path), frame_path.name, frame_path.stem)
    for key in lookup_keys:
        if key in index:
            return index[key]
    raise KeyError(f"Missing detections for frame_id={frame_id} path={frame_path}")


def _frame_id_for_payload(frame_payload: Dict[str, Any]) -> str:
    path = frame_payload.get("path")
    if path:
        return Path(str(path)).stem
    index = frame_payload.get("index")
    if index is None:
        raise ValueError(f"Frame payload is missing both path and index: {frame_payload!r}")
    return f"frame_{int(index):06d}"


def _selected_bounding_box_id(result: Dict[str, Any]) -> int | None:
    value = result.get("bounding_box_id")
    if value is None:
        value = result.get("bbox_id")
    if value is None:
        value = result.get("target_id")
    if value is None:
        return None
    return int(value)


def _bbox_for_selection(
    result: Dict[str, Any],
    detections: List[Dict[str, Any]],
) -> List[int] | None:
    bounding_box_id = _selected_bounding_box_id(result)
    if bounding_box_id is None:
        return None
    for detection in detections:
        if int(detection["track_id"]) == bounding_box_id:
            return [int(value) for value in detection["bbox"]]
    if result.get("found"):
        raise ValueError(f"Selected bounding_box_id={bounding_box_id} not present in detections")
    return None


def _latest_result_payload(store: SessionStore, session_id: str) -> Dict[str, Any]:
    session = store.load_session(session_id)
    if session.latest_result_path is None:
        return {}
    return json.loads(Path(session.latest_result_path).read_text(encoding="utf-8"))


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
    detections_index = _load_detection_index(Path(args.detections_file))

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
    frame0_id = _frame_id_for_payload(batch0["frames"][-1])
    init_detections = _detections_for_frame(detections_index, frame0, frame0_id)
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
            "--detections-json",
            json.dumps(init_detections, ensure_ascii=True),
        ]
    )
    init_result = init_main["result"]
    init_pixel_bbox = _bbox_for_selection(init_result, init_detections)
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
            "bounding_box_id": _selected_bounding_box_id(init_result),
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
        latest_frame_id = _frame_id_for_payload(batch["frames"][-1])
        latest_detections = _detections_for_frame(detections_index, latest_frame, latest_frame_id)
        session = store.load_session(args.session_id)
        previous_result = _latest_result_payload(store, args.session_id)

        main_args = [
            sys.executable,
            str(MAIN_AGENT),
            "--task",
            "track",
            "--env-file",
            args.env_file,
            "--memory",
            store.read_memory(args.session_id),
            "--detections-json",
            json.dumps(latest_detections, ensure_ascii=True),
        ]
        latest_bounding_box_id = _selected_bounding_box_id(previous_result)
        if latest_bounding_box_id is not None:
            main_args.extend(["--latest-bounding-box-id", str(latest_bounding_box_id)])
        if session.latest_confirmed_frame_path:
            main_args.extend(["--image-path", session.latest_confirmed_frame_path])
        main_args.extend(["--image-path", str(latest_frame)])
        track_main = _run_json(main_args)
        track_result = track_main["result"]
        track_pixel_bbox = _bbox_for_selection(track_result, latest_detections)
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
                "bounding_box_id": _selected_bounding_box_id(track_result),
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
