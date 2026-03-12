#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.robot_stream import (
    RobotDetection,
    RobotFrame,
    RobotIngestEvent,
    append_event_jsonl,
    current_timestamp_ms,
    generate_session_id,
    is_camera_source,
    normalize_source,
    post_event,
    probe_video_fps,
    save_frame_image,
    video_timestamp_seconds,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lightweight robot-side ingestion runner for video files or camera input."
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Video file path or camera index such as 0.",
    )
    parser.add_argument(
        "--output-dir",
        default="./runtime/robot-run",
        help="Directory used to store sampled frames and events.jsonl.",
    )
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--device-id", default="robot_01")
    parser.add_argument(
        "--text",
        default="",
        help="Initialization text payload attached to the first emitted event.",
    )
    parser.add_argument(
        "--ongoing-text",
        default="持续跟踪",
        help="Text payload attached to follow-up events after the first initialization event.",
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:8001/api/v1/robot/ingest")
    parser.add_argument(
        "--backend-timeout-seconds",
        type=float,
        default=310.0,
        help="HTTP timeout used when waiting for backend to reply after agent processing.",
    )
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--tracker", default=None)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--sample-every", type=int, default=1)
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=3.0,
        help="Minimum wall-clock seconds between emitted robot events.",
    )
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--person-class-id", type=int, default=0)
    return parser.parse_args()


def _load_yolo():
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Missing robot-side dependencies. Install ultralytics and opencv-python "
            "before running scaffold/cli/run_robot_stream.py."
        ) from exc
    return YOLO


def _extract_person_detections(result: Any, person_class_id: int) -> List[RobotDetection]:
    boxes = getattr(result, "boxes", None)
    if boxes is None or boxes.xyxy is None or boxes.conf is None or boxes.cls is None:
        return []

    xyxy = boxes.xyxy.int().tolist()
    confidences = boxes.conf.tolist()
    class_ids = boxes.cls.int().tolist()
    track_ids = boxes.id.int().tolist() if boxes.id is not None else [index for index in range(len(xyxy))]

    detections: List[RobotDetection] = []
    for index, bbox in enumerate(xyxy):
        if class_ids[index] != person_class_id:
            continue
        detections.append(
            RobotDetection(
                track_id=int(track_ids[index]),
                bbox=[int(value) for value in bbox],
                score=float(confidences[index]),
            )
        )
    return detections


def _should_emit_event(
    frame_index: int,
    sample_every: int,
    now_monotonic: float,
    next_emit_at: float,
) -> bool:
    if frame_index % sample_every != 0:
        return False
    return now_monotonic >= next_emit_at


def _should_emit_video_sample(
    frame_index: int,
    sample_every: int,
    fps: float,
    next_video_emit_at: float,
) -> bool:
    if frame_index % sample_every != 0:
        return False
    return video_timestamp_seconds(frame_index, fps) >= next_video_emit_at


def main() -> int:
    args = parse_args()
    if args.sample_every <= 0:
        raise ValueError("--sample-every must be positive")
    if args.interval_seconds <= 0:
        raise ValueError("--interval-seconds must be positive")
    if args.backend_timeout_seconds <= 0:
        raise ValueError("--backend-timeout-seconds must be positive")
    if args.max_events is not None and args.max_events <= 0:
        raise ValueError("--max-events must be positive when provided")

    output_dir = Path(args.output_dir)
    frames_dir = output_dir / "frames"
    events_path = output_dir / "events.jsonl"
    session_id = args.session_id or generate_session_id()

    YOLO = _load_yolo()
    model = YOLO(args.model)

    source = normalize_source(args.source)
    source_is_camera = is_camera_source(source)
    video_fps = None if source_is_camera else probe_video_fps(Path(str(source)))

    track_kwargs = {
        "source": source,
        "conf": args.conf,
        "imgsz": args.imgsz,
        "persist": True,
        "stream": True,
        "verbose": False,
    }
    if args.tracker:
        track_kwargs["tracker"] = args.tracker

    emitted_events = 0
    next_emit_at = 0.0
    next_video_emit_at = 0.0
    for frame_index, result in enumerate(model.track(**track_kwargs), start=1):
        now_monotonic = time.monotonic()
        if source_is_camera:
            if not _should_emit_event(
                frame_index=frame_index,
                sample_every=args.sample_every,
                now_monotonic=now_monotonic,
                next_emit_at=next_emit_at,
            ):
                continue
        else:
            if video_fps is None:
                raise RuntimeError("Video FPS must be available for file playback mode")
            if not _should_emit_video_sample(
                frame_index=frame_index,
                sample_every=args.sample_every,
                fps=video_fps,
                next_video_emit_at=next_video_emit_at,
            ):
                continue

        frame_id = f"frame_{emitted_events:06d}"
        frame_path = frames_dir / f"{frame_id}.jpg"
        save_frame_image(result.orig_img, frame_path)

        event = RobotIngestEvent(
            session_id=session_id,
            device_id=args.device_id,
            frame=RobotFrame(
                frame_id=frame_id,
                timestamp_ms=current_timestamp_ms(),
                image_path=str(frame_path),
            ),
            detections=_extract_person_detections(result, person_class_id=args.person_class_id),
            text=args.text if emitted_events == 0 else args.ongoing_text,
        )
        append_event_jsonl(events_path, event)

        backend_status = None
        if args.backend_url:
            backend_response = post_event(
                args.backend_url,
                event,
                timeout_seconds=args.backend_timeout_seconds,
            )
            backend_status = backend_response["status"]

        summary = {
            "session_id": session_id,
            "frame_id": frame_id,
            "image_path": str(frame_path),
            "detection_count": len(event.detections),
            "backend_status": backend_status,
        }
        print(json.dumps(summary, ensure_ascii=True), flush=True)

        emitted_events += 1
        next_emit_at = now_monotonic + args.interval_seconds
        if not source_is_camera:
            next_video_emit_at += args.interval_seconds
        if args.max_events is not None and emitted_events >= args.max_events:
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
