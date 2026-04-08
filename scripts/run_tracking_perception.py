#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterator, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.perception import LocalPerceptionService
from backend.perception.stream import (
    RobotFrame,
    RobotIngestEvent,
    current_timestamp_ms,
    is_camera_source,
    normalize_source,
    probe_video_fps,
    save_frame_image,
    video_timestamp_seconds,
)
from backend.project_paths import resolve_project_path

DEFAULT_CAMERA_SOURCE = "0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Perception writer. Captures frames from a local camera or video source, resets "
            "global perception state on start, and writes the shared world snapshot."
        )
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_CAMERA_SOURCE,
        help=(
            "Video file path or explicit camera index such as 0. "
            "Defaults to camera index 0."
        ),
    )
    parser.add_argument(
        "--observation-text",
        default="",
        help="Optional observation note stored with each sampled event.",
    )
    parser.add_argument(
        "--state-root",
        default="./.runtime/agent-runtime",
        help="Shared state root used by the perception writer and PI reader.",
    )
    parser.add_argument(
        "--vid-stride",
        type=int,
        default=1,
        help="Read every Nth source frame for video files.",
    )
    parser.add_argument("--sample-every", type=int, default=1)
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=1.0,
        help="Minimum seconds between emitted observations.",
    )
    parser.add_argument(
        "--realtime-playback",
        action="store_true",
        help="For video files, sleep for interval-seconds after each emitted observation.",
    )
    parser.add_argument(
        "--pause-after-first-event-file",
        default=None,
        help="Optional sentinel file. If it exists after the first emitted event, pause until it is removed.",
    )
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument(
        "--observation-window-seconds",
        type=float,
        default=5.0,
        help="How much recent camera perception to keep in the persisted observation window.",
    )
    parser.add_argument(
        "--keyframe-retention-seconds",
        type=float,
        default=10.0,
        help="How much keyframe history to keep on disk.",
    )

    return parser.parse_args()


def _load_cv2():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Missing robot-side dependencies. Install opencv-python before running scripts/run_perception.py."
        ) from exc
    return cv2


def _probe_camera_indices(max_index: int = 5) -> list[int]:
    cv2 = _load_cv2()
    available: list[int] = []
    for index in range(max_index):
        capture = cv2.VideoCapture(index)
        try:
            if capture.isOpened():
                ok, _frame = capture.read()
                if ok:
                    available.append(index)
        finally:
            capture.release()
    return available


def _assert_camera_source(source: int) -> None:
    cv2 = _load_cv2()
    capture = cv2.VideoCapture(source)
    try:
        if not capture.isOpened():
            available_cameras = _probe_camera_indices()
            raise RuntimeError(
                "Failed to open camera source index "
                f"{source}. On macOS this is often caused by camera permission denied or another app holding the device. "
                f"Available readable indices from 0..4: {available_cameras}. "
                "Try another index such as 1 or 2, or pass a file path to --source for debugging."
            )

        ready = False
        for _ in range(5):
            ok, frame = capture.read()
            if ok and frame is not None:
                ready = True
                break
            time.sleep(0.2)
        if not ready:
            raise RuntimeError(
                "Opened camera source but failed to read a frame. "
                "The device might be blocked by another process or not initialized yet."
            )
    finally:
        capture.release()


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


def _iter_frames(source: Any, *, vid_stride: int) -> Iterator[Tuple[int, Any]]:
    cv2 = _load_cv2()
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video source: {source}")

    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            frame_index += 1
            if vid_stride > 1 and frame_index % vid_stride != 0:
                continue
            yield frame_index, frame
    finally:
        capture.release()


def _prepare_perception_writer(*, perception_service: LocalPerceptionService) -> None:
    perception_service.prepare(fresh_state=True)


async def _run_perception_writer(
    args: argparse.Namespace,
    *,
    perception_service: LocalPerceptionService,
    frame_stream: Iterator[Tuple[int, Any]],
    video_fps: float | None,
    source_is_camera: bool,
) -> int:
    emitted_events = 0
    last_timestamp_ms: int | None = None
    next_emit_at = 0.0
    next_video_emit_at = 0.0
    next_wall_emit_at: float | None = None
    source_started_at_ms = current_timestamp_ms()
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

    for frame_index, frame_bgr in frame_stream:
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
            detections=[],
            text=str(args.observation_text).strip(),
        )
        last_timestamp_ms = int(event.frame.timestamp_ms)
        snapshot = await asyncio.to_thread(perception_service.write_observation, event)
        persisted_image_path_value = str(((snapshot.get("latest_frame") or {}).get("image_path")) or "").strip()
        persisted_image_path = None if not persisted_image_path_value else Path(persisted_image_path_value)
        if persisted_image_path is not None and persisted_image_path != frame_path and frame_path.exists():
            frame_path.unlink()

        print(
            json.dumps(
                {
                    "frame_id": frame_id,
                    "timestamp_ms": timestamp_ms,
                    "image_path": str(frame_path if persisted_image_path is None else persisted_image_path),
                    "ingest_status": 200,
                },
                ensure_ascii=True,
            ),
            flush=True,
        )

        if emitted_events == 0 and pause_after_first_event_file is not None:
            while pause_after_first_event_file.exists():
                await asyncio.sleep(0.1)

        emitted_events += 1
        next_emit_at = now_monotonic + args.interval_seconds
        if not source_is_camera:
            next_video_emit_at += args.interval_seconds
            if args.realtime_playback:
                if next_wall_emit_at is None:
                    next_wall_emit_at = now_monotonic + args.interval_seconds
                else:
                    next_wall_emit_at += args.interval_seconds
                remaining_sleep = max(0.0, next_wall_emit_at - time.monotonic())
                if remaining_sleep > 0:
                    await asyncio.sleep(remaining_sleep)
        if args.max_events is not None and emitted_events >= args.max_events:
            break

    perception_service.update_stream_status(
        status="completed",
        ended_at_ms=last_timestamp_ms if last_timestamp_ms is not None else current_timestamp_ms(),
    )
    return 0


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

    state_root = resolve_project_path(args.state_root)
    perception_service = LocalPerceptionService(
        state_root=state_root,
        observation_window_seconds=args.observation_window_seconds,
        save_frame_every_seconds=args.interval_seconds,
        keyframe_retention_seconds=args.keyframe_retention_seconds,
    )
    _prepare_perception_writer(perception_service=perception_service)

    source = normalize_source(str(args.source).strip())
    if isinstance(source, str):
        source = str(resolve_project_path(source))
    source_is_camera = is_camera_source(source)
    video_fps = None if source_is_camera else probe_video_fps(Path(str(source)))

    if source_is_camera:
        _assert_camera_source(int(source))
    frame_stream = _iter_frames(source, vid_stride=args.vid_stride)

    return await _run_perception_writer(
        args,
        perception_service=perception_service,
        frame_stream=frame_stream,
        video_fps=video_fps,
        source_is_camera=source_is_camera,
    )


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    raise SystemExit(main())
