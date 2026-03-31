#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.perception import LocalPerceptionService
from backend.perception.stream import (
    RobotDetection,
    RobotFrame,
    RobotIngestEvent,
    append_event_jsonl,
    current_timestamp_ms,
    generate_session_id,
    is_camera_source,
    normalize_source,
    probe_video_fps,
    save_frame_image,
    trim_event_jsonl,
    video_timestamp_seconds,
)
from backend.project_paths import resolve_project_path

DEFAULT_PERSON_MODEL = "yolov8n.pt"
DEFAULT_CAMERA_SOURCE = "camera"
VIDEO_TRACK_FPS = 8.0
CAMERA_SOURCE_ALIASES = frozenset({"camera", "builtin-camera", "default-camera"})
PREFERRED_CAMERA_NAME_HINTS = ("built-in", "facetime", "integrated", "internal")
DEPRIORITIZED_CAMERA_NAME_HINTS = (
    "demo",
    "virtual",
    "obs",
    "camo",
    "continuity",
    "iphone",
    "desk view",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Tracking perception writer. Runs person detection over the local camera by default, "
            "or over an explicit video file/camera source, then writes sampled observations into "
            "the shared perception store."
        )
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_CAMERA_SOURCE,
        help=(
            "Video file path, camera index such as 0, or 'camera'. Defaults to the local "
            "computer camera and avoids demo/virtual devices when detectable."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="./.runtime/tracking-perception",
        help="Directory used to store sampled frames and events.jsonl.",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Optional. If omitted, create a random fresh session and mark it active.",
    )
    parser.add_argument(
        "--fresh-session",
        action="store_true",
        help="When --session-id is provided and already exists, reset it before writing new perception events.",
    )
    parser.add_argument("--device-id", default="robot_01")
    parser.add_argument(
        "--observation-text",
        default="",
        help="Optional observation note stored with each sampled event. This is not appended to chat history.",
    )
    parser.add_argument(
        "--state-root",
        default="./.runtime/agent-runtime",
        help="Shared state root used by the perception service and agent runtime.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_PERSON_MODEL,
        help="Ultralytics model weights for person tracking inference. Defaults to YOLOv8n via yolov8n.pt.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Ultralytics inference device, for example 'mps', 'cpu', or '0'.",
    )
    parser.add_argument("--tracker", default=None)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument(
        "--imgsz",
        type=int,
        default=None,
        help="Optional Ultralytics inference size. Leave unset to use the original frame size.",
    )
    parser.add_argument(
        "--vid-stride",
        type=int,
        default=1,
        help="Run inference on every Nth frame for video files. Higher values reduce compute.",
    )
    parser.add_argument("--sample-every", type=int, default=1)
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=1.0,
        help="Minimum wall-clock seconds between emitted observations.",
    )
    parser.add_argument(
        "--realtime-playback",
        action="store_true",
        help="For video files, sleep for interval-seconds after each emitted observation so the viewer updates in wall-clock time.",
    )
    parser.add_argument(
        "--pause-after-first-event-file",
        default=None,
        help="Optional sentinel file. If it exists after the first emitted event, pause perception until the file is removed.",
    )
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--max-event-log-lines", type=int, default=300)
    parser.add_argument("--person-class-id", type=int, default=0)
    parser.add_argument(
        "--observation-window-seconds",
        type=float,
        default=5.0,
        help="How much recent camera perception to keep in the in-process observation window.",
    )
    parser.add_argument(
        "--save-keyframe-every-seconds",
        type=float,
        default=1.0,
        help="How often to save shared perception keyframes.",
    )
    parser.add_argument(
        "--keyframe-retention-seconds",
        type=float,
        default=10.0,
        help="How much keyframe history to keep on disk.",
    )
    return parser.parse_args()


def _load_yolo():
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Missing robot-side dependencies. Install ultralytics and opencv-python "
            "before running scripts/run_tracking_perception.py."
        ) from exc
    return YOLO


def _load_cv2():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Missing robot-side dependencies. Install ultralytics and opencv-python "
            "before running scripts/run_tracking_perception.py."
        ) from exc
    return cv2


def _is_default_camera_source(raw_source: str) -> bool:
    return str(raw_source or "").strip().lower() in CAMERA_SOURCE_ALIASES


def _avfoundation_video_devices() -> List[tuple[int, str]]:
    if sys.platform != "darwin":
        return []
    try:
        completed = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    devices: List[tuple[int, str]] = []
    in_video_section = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "AVFoundation video devices:" in line:
            in_video_section = True
            continue
        if "AVFoundation audio devices:" in line:
            in_video_section = False
            continue
        if not in_video_section:
            continue
        match = re.search(r"\[(\d+)\]\s+(.+)$", line)
        if match is None:
            continue
        devices.append((int(match.group(1)), match.group(2).strip()))
    return devices


def _preferred_camera_index() -> int:
    devices = _avfoundation_video_devices()
    if not devices:
        return 0

    def _name_score(name: str) -> int:
        lowered = name.lower()
        if any(token in lowered for token in DEPRIORITIZED_CAMERA_NAME_HINTS):
            return 2
        if any(token in lowered for token in PREFERRED_CAMERA_NAME_HINTS):
            return 0
        return 1

    ranked = sorted(devices, key=lambda item: (_name_score(item[1]), item[0]))
    return ranked[0][0]


def _resolve_source(raw_source: str) -> Any:
    cleaned = str(raw_source or "").strip()
    if _is_default_camera_source(cleaned):
        return _preferred_camera_index()
    return normalize_source(cleaned)


def _normalize_xyxy_bbox(bbox: List[int]) -> List[int]:
    x1, y1, x2, y2 = [int(value) for value in bbox]
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    return [left, top, right, bottom]


def _prune_frame_dir(frame_dir: Path, *, keep_last: int) -> None:
    if keep_last <= 0 or not frame_dir.exists():
        return
    frames = sorted(
        [path for path in frame_dir.iterdir() if path.is_file()],
        key=lambda path: path.stat().st_mtime_ns,
    )
    while len(frames) > keep_last:
        expired = frames.pop(0)
        try:
            expired.unlink()
        except FileNotFoundError:
            continue


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
                bbox=_normalize_xyxy_bbox(bbox),
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


def _configure_device_runtime(device: str | None) -> None:
    normalized = (device or "").strip().lower()
    if normalized != "mps":
        return
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"):
        return
    os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    print(
        "Enabled PYTORCH_ENABLE_MPS_FALLBACK=1 for MPS unsupported ops such as torchvision NMS.",
        file=sys.stderr,
        flush=True,
    )


def _video_frame_step(fps: float, vid_stride: int) -> int:
    base_step = max(1, round(fps / VIDEO_TRACK_FPS))
    return max(1, base_step * vid_stride)


def _track_kwargs(
    *,
    source: Any,
    args: argparse.Namespace,
    stream: bool,
    persist: bool,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "source": source,
        "conf": args.conf,
        "persist": persist,
        "stream": stream,
        "verbose": False,
        "classes": [args.person_class_id],
    }
    if args.imgsz is not None:
        kwargs["imgsz"] = args.imgsz
    if args.device:
        kwargs["device"] = args.device
    if args.tracker:
        kwargs["tracker"] = args.tracker
    return kwargs


def _results_for_video_file(
    *,
    model: Any,
    video_path: Path,
    fps: float,
    args: argparse.Namespace,
):
    cv2 = _load_cv2()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video source: {video_path}")

    try:
        step = _video_frame_step(fps=fps, vid_stride=args.vid_stride)
        next_frame_number = 0
        frame_number = 0
        while True:
            if frame_number < next_frame_number:
                ok = capture.grab()
                if not ok:
                    break
                frame_number += 1
                continue

            ok, frame = capture.read()
            if not ok:
                break
            results = model.track(
                **_track_kwargs(
                    source=frame,
                    args=args,
                    stream=False,
                    persist=True,
                )
            )
            if not results:
                break
            yield frame_number + 1, results[0]
            frame_number += 1
            next_frame_number += step
    finally:
        capture.release()


async def _run_perception_writer(
    args: argparse.Namespace,
    result_stream,
    output_dir: Path,
    session_id: str,
    video_fps: float | None,
    source_is_camera: bool,
) -> int:
    events_path = output_dir / "events.jsonl"
    emitted_events = 0
    last_timestamp_ms: int | None = None
    next_emit_at = 0.0
    next_video_emit_at = 0.0
    next_wall_emit_at: float | None = None
    perception_service = LocalPerceptionService(
        state_root=Path(args.state_root),
        observation_window_seconds=args.observation_window_seconds,
        save_frame_every_seconds=args.save_keyframe_every_seconds,
        keyframe_retention_seconds=args.keyframe_retention_seconds,
    )
    state_frames_dir = Path(args.state_root) / "perception" / "sessions" / session_id / "frames"
    state_frames_dir.mkdir(parents=True, exist_ok=True)
    pause_after_first_event_file = (
        None
        if args.pause_after_first_event_file in (None, "")
        else resolve_project_path(args.pause_after_first_event_file)
    )

    for frame_index, result in result_stream:
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
        frame_path = state_frames_dir / f"{frame_id}.jpg"
        save_frame_image(result.orig_img, frame_path)
        _prune_frame_dir(
            state_frames_dir,
            keep_last=max(1, int(args.keyframe_retention_seconds / args.save_keyframe_every_seconds)),
        )

        event = RobotIngestEvent(
            session_id=session_id,
            device_id=args.device_id,
            frame=RobotFrame(
                frame_id=frame_id,
                timestamp_ms=current_timestamp_ms(),
                image_path=str(frame_path),
            ),
            detections=_extract_person_detections(result, person_class_id=args.person_class_id),
            text=str(args.observation_text).strip(),
        )
        last_timestamp_ms = int(event.frame.timestamp_ms)
        append_event_jsonl(events_path, event)
        trim_event_jsonl(events_path, keep_last_lines=args.max_event_log_lines)
        snapshot = await asyncio.to_thread(
            perception_service.write_observation,
            event,
            request_function="observation",
            record_conversation=False,
        )
        persisted_image_path_value = str(
            (
                (snapshot.get("latest_camera_observation") or {}).get("payload") or {}
            ).get("image_path", "")
        ).strip()
        persisted_image_path = None if not persisted_image_path_value else Path(persisted_image_path_value)
        if persisted_image_path is not None and persisted_image_path != frame_path and frame_path.exists():
            frame_path.unlink()

        summary = {
            "session_id": session_id,
            "frame_id": frame_id,
            "image_path": str(frame_path if persisted_image_path is None else persisted_image_path),
            "detection_count": len(event.detections),
            "ingest_status": 200,
        }
        print(json.dumps(summary, ensure_ascii=True), flush=True)

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
        session_id,
        status="completed",
        ended_at_ms=last_timestamp_ms if last_timestamp_ms is not None else current_timestamp_ms(),
    )
    return 0


def _prepare_perception_session(
    *,
    perception_service: LocalPerceptionService,
    session_id: str,
    device_id: str,
    fresh_session: bool,
) -> None:
    perception_service.prepare_session(
        session_id=session_id,
        device_id=device_id,
        fresh_session=fresh_session,
        mark_active=True,
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
    if args.max_event_log_lines <= 0:
        raise ValueError("--max-event-log-lines must be positive")
    if args.observation_window_seconds <= 0:
        raise ValueError("--observation-window-seconds must be positive")
    if args.save_keyframe_every_seconds <= 0:
        raise ValueError("--save-keyframe-every-seconds must be positive")
    if args.keyframe_retention_seconds <= 0:
        raise ValueError("--keyframe-retention-seconds must be positive")

    output_dir = resolve_project_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "events.jsonl").write_text("", encoding="utf-8")
    session_id = args.session_id or generate_session_id()
    state_root = resolve_project_path(args.state_root)
    perception_service = LocalPerceptionService(
        state_root=state_root,
        observation_window_seconds=args.observation_window_seconds,
        save_frame_every_seconds=args.save_keyframe_every_seconds,
        keyframe_retention_seconds=args.keyframe_retention_seconds,
    )
    _prepare_perception_session(
        perception_service=perception_service,
        session_id=session_id,
        device_id=args.device_id,
        fresh_session=bool(args.fresh_session or args.session_id in (None, "")),
    )

    _configure_device_runtime(args.device)
    YOLO = _load_yolo()
    model = YOLO(args.model)

    source = _resolve_source(args.source)
    if _is_default_camera_source(args.source):
        print(
            json.dumps(
                {
                    "status": "camera_source_selected",
                    "requested_source": str(args.source),
                    "resolved_source": source,
                },
                ensure_ascii=True,
            ),
            flush=True,
        )
    if isinstance(source, str):
        source = str(resolve_project_path(source))
    source_is_camera = is_camera_source(source)
    video_fps = None if source_is_camera else probe_video_fps(Path(str(source)))

    if source_is_camera:
        result_stream = enumerate(
            model.track(
                **_track_kwargs(
                    source=source,
                    args=args,
                    stream=True,
                    persist=True,
                )
            ),
            start=1,
        )
    else:
        if video_fps is None:
            raise RuntimeError("Video FPS must be available for file playback mode")
        result_stream = _results_for_video_file(
            model=model,
            video_path=Path(str(source)),
            fps=video_fps,
            args=args,
        )

    return await _run_perception_writer(
        args,
        result_stream,
        output_dir,
        session_id,
        video_fps,
        source_is_camera,
    )


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    raise SystemExit(main())
