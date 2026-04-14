#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Iterator, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.infra.paths import resolve_project_path
from world import (
    DEFAULT_PERSON_CLASS_ID,
    DEFAULT_SYSTEM1_MODEL,
    DEFAULT_SYSTEM1_TRACKER,
    System1Tracker,
)
from world.perception import LocalPerceptionService
from world.perception.stream import (
    DEFAULT_CAMERA_SOURCE,
    RobotFrame,
    RobotIngestEvent,
    assert_camera_source,
    current_timestamp_ms,
    is_camera_source,
    iter_frames,
    normalize_source,
    probe_video_fps,
    save_frame_image,
    should_emit_event,
    should_emit_video_sample,
    target_video_emit_at,
    video_timestamp_seconds,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Start the always-on write environment. Pass a camera index such as 0 or a video file path. "
            "Other runtime parameters stay on project defaults."
        )
    )
    parser.add_argument("--source", default=DEFAULT_CAMERA_SOURCE, help="Camera index like 0, or a video file path.")
    parser.add_argument("--observation-text", default="", help=argparse.SUPPRESS)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime", help=argparse.SUPPRESS)
    parser.add_argument("--vid-stride", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--sample-every", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--interval-seconds", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--realtime-playback", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pause-after-first-event-file", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--max-events", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--observation-window-seconds", type=float, default=5.0, help=argparse.SUPPRESS)
    parser.add_argument("--keyframe-retention-seconds", type=float, default=10.0, help=argparse.SUPPRESS)
    parser.add_argument("--system1-model", default=DEFAULT_SYSTEM1_MODEL, help=argparse.SUPPRESS)
    parser.add_argument("--system1-tracker", default=DEFAULT_SYSTEM1_TRACKER, help=argparse.SUPPRESS)
    parser.add_argument("--system1-device", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--system1-conf", type=float, default=0.25, help=argparse.SUPPRESS)
    parser.add_argument("--system1-imgsz", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--system1-person-class-id", type=int, default=DEFAULT_PERSON_CLASS_ID, help=argparse.SUPPRESS)
    parser.add_argument("--system1-result-window-seconds", type=float, default=5.0, help=argparse.SUPPRESS)
    parser.add_argument(
        "--disable-system1",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    source = normalize_source(str(args.source).strip())
    if not is_camera_source(source):
        args.realtime_playback = True
    return args


def _prepare_world_writer(
    *,
    perception_service: LocalPerceptionService,
    system1_service: Optional[LocalPerceptionService],
    system1_tracker: Optional[System1Tracker],
) -> None:
    perception_service.prepare(fresh_state=True)
    if system1_service is not None:
        system1_service.prepare_system1(
            fresh_state=True,
            model_info=None if system1_tracker is None else system1_tracker.model_info(),
        )


async def _write_system1_result(
    *,
    system1_service: Optional[LocalPerceptionService],
    frame_id: str,
    timestamp_ms: int,
    image_path: Path,
    detections: list[Any],
) -> dict | None:
    if system1_service is None:
        return None
    result = {
        "frame_id": frame_id,
        "timestamp_ms": int(timestamp_ms),
        "image_path": str(image_path),
        "detections": [
            {
                "track_id": None if int(detection.track_id) < 0 else int(detection.track_id),
                "bbox": [int(value) for value in detection.bbox],
                "score": float(detection.score),
                "label": str(detection.label).strip() or "person",
            }
            for detection in list(detections or [])
        ],
    }
    snapshot = await asyncio.to_thread(system1_service.write_frame_result, result)
    return dict(snapshot.get("latest_frame_result") or {})


async def _run_world_writer(
    args: argparse.Namespace,
    *,
    perception_service: LocalPerceptionService,
    system1_service: Optional[LocalPerceptionService],
    system1_tracker: Optional[System1Tracker],
    frame_stream: Iterator[Tuple[int, Any]],
    video_fps: float | None,
    source_is_camera: bool,
) -> int:
    emitted_events = 0
    last_timestamp_ms: int | None = None
    next_emit_at = 0.0
    next_video_emit_at = 0.0
    source_started_at_ms = current_timestamp_ms()
    source_started_monotonic = time.monotonic()
    paused_seconds = 0.0
    state_root = resolve_project_path(args.state_root)
    incoming_dir = state_root / "perception" / "incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    for path in incoming_dir.glob("*"):
        if path.is_file():
            path.unlink()
    pause_after_first_event_file = (
        None
        if args.pause_after_first_event_file in (None, "")
        else resolve_project_path(args.pause_after_first_event_file)
    )
    latest_tracker_detections = []

    for frame_index, frame_bgr in frame_stream:
        if system1_tracker is not None:
            latest_tracker_detections = await asyncio.to_thread(system1_tracker.track_detections, frame_bgr=frame_bgr)
        now_monotonic = time.monotonic()
        if source_is_camera:
            if not should_emit_event(
                frame_index=frame_index,
                sample_every=args.sample_every,
                now_monotonic=now_monotonic,
                next_emit_at=next_emit_at,
            ):
                continue
        else:
            if video_fps is None:
                raise RuntimeError("Video FPS must be available for file playback mode")
            scheduled_video_emit_at = target_video_emit_at(
                next_video_emit_at=next_video_emit_at,
                realtime_playback=bool(args.realtime_playback),
                source_started_monotonic=source_started_monotonic,
                now_monotonic=now_monotonic,
                paused_seconds=paused_seconds,
            )
            if not should_emit_video_sample(
                frame_index=frame_index,
                sample_every=args.sample_every,
                fps=video_fps,
                next_video_emit_at=scheduled_video_emit_at,
            ):
                continue

        frame_id = f"frame_{emitted_events:06d}"
        timestamp_ms = (
            current_timestamp_ms()
            if source_is_camera
            else source_started_at_ms + round(video_timestamp_seconds(frame_index, video_fps) * 1000)
        )
        frame_path = incoming_dir / f"{frame_id}.jpg"
        save_frame_image(frame_bgr, frame_path)

        event = RobotIngestEvent(
            session_id="",
            device_id="",
            frame=RobotFrame(
                frame_id=frame_id,
                timestamp_ms=timestamp_ms,
                image_path=str(frame_path),
            ),
            detections=list(latest_tracker_detections),
            text=str(args.observation_text).strip(),
        )
        last_timestamp_ms = int(event.frame.timestamp_ms)
        perception_snapshot = await asyncio.to_thread(perception_service.write_observation, event)
        persisted_image_path_value = str(((perception_snapshot.get("latest_frame") or {}).get("image_path")) or "").strip()
        persisted_image_path = None if not persisted_image_path_value else Path(persisted_image_path_value)
        system1_result = await _write_system1_result(
            system1_service=system1_service,
            frame_id=frame_id,
            timestamp_ms=timestamp_ms,
            image_path=frame_path if persisted_image_path is None else persisted_image_path,
            detections=list(latest_tracker_detections),
        )
        if persisted_image_path is not None and persisted_image_path != frame_path and frame_path.exists():
            frame_path.unlink()

        print(
            _perception_log_line(
                frame_id=frame_id,
                timestamp_ms=timestamp_ms,
                image_path=frame_path if persisted_image_path is None else persisted_image_path,
            ),
            flush=True,
        )
        print(
            _system1_log_line(
                frame_id=frame_id,
                system1_result=system1_result,
            ),
            flush=True,
        )

        if emitted_events == 0 and pause_after_first_event_file is not None:
            pause_started_at = time.monotonic()
            while pause_after_first_event_file.exists():
                await asyncio.sleep(0.1)
            paused_seconds += max(0.0, time.monotonic() - pause_started_at)

        emitted_events += 1
        next_emit_at = now_monotonic + args.interval_seconds
        if not source_is_camera:
            next_video_emit_at = video_timestamp_seconds(frame_index, video_fps) + args.interval_seconds
            if args.realtime_playback:
                remaining_sleep = max(
                    0.0,
                    (source_started_monotonic + paused_seconds + next_video_emit_at) - time.monotonic(),
                )
                if remaining_sleep > 0:
                    await asyncio.sleep(remaining_sleep)
        if args.max_events is not None and emitted_events >= args.max_events:
            break

    perception_service.update_stream_status(
        status="completed",
        ended_at_ms=last_timestamp_ms if last_timestamp_ms is not None else current_timestamp_ms(),
    )
    if system1_service is not None:
        system1_service.update_stream_status(
            status="completed",
            ended_at_ms=last_timestamp_ms if last_timestamp_ms is not None else current_timestamp_ms(),
        )
    return 0


def _build_system1_services(
    args: argparse.Namespace,
    *,
    state_root: Path,
) -> tuple[Optional[LocalPerceptionService], Optional[System1Tracker]]:
    if args.disable_system1:
        return None, None
    system1_service = LocalPerceptionService(
        state_root=state_root,
        result_window_seconds=args.system1_result_window_seconds,
    )
    tracker = System1Tracker(
        model_path=resolve_project_path(args.system1_model),
        tracker=str(args.system1_tracker or "").strip() or None,
        device=None if args.system1_device in (None, "") else str(args.system1_device),
        conf=float(args.system1_conf),
        imgsz=args.system1_imgsz,
        person_class_id=int(args.system1_person_class_id),
    )
    return system1_service, tracker


def _perception_log_line(
    *,
    frame_id: str,
    timestamp_ms: int,
    image_path: Path,
) -> str:
    return (
        f"视觉感知：frame_id={frame_id}, "
        f"timestamp_ms={int(timestamp_ms)}, "
        f"image_path={str(image_path)}"
    )


def _system1_log_line(
    *,
    frame_id: str,
    system1_result: dict | None,
) -> str:
    detections = [] if system1_result is None else list(system1_result.get("detections") or [])
    track_ids = [
        int(detection["track_id"])
        for detection in detections
        if isinstance(detection, dict) and detection.get("track_id") not in (None, "")
    ]
    return (
        f"yolo+bytetrack：frame_id={frame_id}, "
        f"detection_count={len(detections)}, "
        f"track_ids={track_ids}"
    )


async def _async_main() -> int:
    args = parse_args()
    if args.sample_every <= 0:
        raise ValueError("--sample-every must be positive")
    if args.vid_stride <= 0:
        raise ValueError("--vid-stride must be positive")
    if args.interval_seconds <= 0:
        raise ValueError("--interval-seconds must be positive")
    if args.max_events is not None and args.max_events <= 0:
        raise ValueError("--max-events must be positive when provided")
    if args.observation_window_seconds <= 0:
        raise ValueError("--observation-window-seconds must be positive")
    if args.keyframe_retention_seconds <= 0:
        raise ValueError("--keyframe-retention-seconds must be positive")
    if args.system1_result_window_seconds <= 0:
        raise ValueError("--system1-result-window-seconds must be positive")

    state_root = resolve_project_path(args.state_root)
    perception_service = LocalPerceptionService(
        state_root=state_root,
        observation_window_seconds=args.observation_window_seconds,
        result_window_seconds=args.system1_result_window_seconds,
        save_frame_every_seconds=args.interval_seconds,
        keyframe_retention_seconds=args.keyframe_retention_seconds,
    )
    system1_service, system1_tracker = _build_system1_services(args, state_root=state_root)
    _prepare_world_writer(
        perception_service=perception_service,
        system1_service=system1_service,
        system1_tracker=system1_tracker,
    )

    source = normalize_source(str(args.source).strip())
    if isinstance(source, str):
        source = str(resolve_project_path(source))
    source_is_camera = is_camera_source(source)
    video_fps = None if source_is_camera else probe_video_fps(Path(str(source)))

    if source_is_camera:
        assert_camera_source(int(source))
    frame_stream = iter_frames(source, vid_stride=args.vid_stride)

    return await _run_world_writer(
        args,
        perception_service=perception_service,
        system1_service=system1_service,
        system1_tracker=system1_tracker,
        frame_stream=frame_stream,
        video_fps=video_fps,
        source_is_camera=source_is_camera,
    )


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    raise SystemExit(main())
