#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.robot_stream import (
    RobotDetection,
    RobotFrame,
    RobotIngestEvent,
    append_event_jsonl,
    current_timestamp_ms,
    generate_request_id,
    generate_session_id,
    is_camera_source,
    is_websocket_url,
    normalize_source,
    open_robot_backend_socketio,
    open_robot_backend_websocket,
    post_event,
    post_event_socketio,
    post_event_ws,
    probe_video_fps,
    save_frame_image,
    video_timestamp_seconds,
)
from tracking_agent.service_urls import build_backend_service_url

DEFAULT_PERSON_MODEL = "yolov8m.pt"
VIDEO_TRACK_FPS = 8.0


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
    parser.add_argument(
        "--backend-url",
        default=None,
        help=(
            "Explicit backend address. For socketio-agent use the backend base URL; for "
            "websocket/http modes use the full endpoint. When omitted, the CLI builds one from "
            "--backend-base-url and --backend-protocol."
        ),
    )
    parser.add_argument(
        "--backend-base-url",
        default="http://127.0.0.1:8001",
        help="Backend base address such as http://192.168.1.8:8001 or tracking.example.com:8001.",
    )
    parser.add_argument(
        "--backend-protocol",
        choices=("socketio-agent", "robot-agent", "robot-ingest", "http-ingest"),
        default="socketio-agent",
        help="Which backend ingest interface to target when --backend-url is omitted.",
    )
    parser.add_argument(
        "--backend-timeout-seconds",
        type=float,
        default=310.0,
        help="Timeout used when waiting for the backend to reply after agent processing.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_PERSON_MODEL,
        help="Ultralytics model weights for person tracking inference. Defaults to YOLOv8m via yolov8m.pt.",
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
        default=3.0,
        help="Minimum wall-clock seconds between emitted robot events.",
    )
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--person-class-id", type=int, default=0)
    return parser.parse_args()


def resolve_backend_url(args: argparse.Namespace) -> str:
    explicit_url = str(args.backend_url or "").strip()
    if explicit_url:
        return explicit_url

    channel = {
        "socketio-agent": "socketio_robot_agent",
        "robot-agent": "robot_agent",
        "robot-ingest": "robot_ingest",
        "http-ingest": "robot_http_ingest",
    }[args.backend_protocol]
    return build_backend_service_url(args.backend_base_url, channel=channel)


def _load_yolo():
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Missing robot-side dependencies. Install ultralytics and opencv-python "
            "before running scaffold/cli/run_robot_stream.py."
        ) from exc
    return YOLO


def _load_cv2():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Missing robot-side dependencies. Install ultralytics and opencv-python "
            "before running scaffold/cli/run_robot_stream.py."
        ) from exc
    return cv2


def _normalize_xyxy_bbox(bbox: List[int]) -> List[int]:
    x1, y1, x2, y2 = [int(value) for value in bbox]
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    return [left, top, right, bottom]


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


def _video_frame_step(
    fps: float,
    vid_stride: int,
) -> int:
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
        # Restrict detection to people to reduce detector workload.
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
        step = _video_frame_step(
            fps=fps,
            vid_stride=args.vid_stride,
        )
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


def _log_backend_event(event: Dict[str, Any]) -> None:
    event_type = str(event.get("type", "")).strip()
    if not event_type or event_type == "robot_ingest_result":
        return
    summary = {
        "backend_event": event_type,
        "session_id": event.get("session_id"),
        "frame_id": event.get("frame_id"),
        "stage": event.get("stage"),
        "status": event.get("status"),
    }
    print(json.dumps(summary, ensure_ascii=True), flush=True)


def _websocket_protocol(url: str) -> str:
    path = urlsplit(url).path.rstrip("/")
    if path.endswith("/ws/robot-agent"):
        return "robot_agent"
    return "robot_ingest"


async def _run_backend_stream(
    args: argparse.Namespace,
    result_stream,
    output_dir: Path,
    session_id: str,
    video_fps: float | None,
) -> int:
    frames_dir = output_dir / "frames"
    events_path = output_dir / "events.jsonl"
    emitted_events = 0
    next_emit_at = 0.0
    next_video_emit_at = 0.0
    backend_url = resolve_backend_url(args)
    source_is_camera = is_camera_source(normalize_source(args.source))
    backend_is_socketio = args.backend_protocol == "socketio-agent"
    backend_is_websocket = (not backend_is_socketio) and bool(backend_url) and is_websocket_url(backend_url)
    websocket_protocol = None if not backend_is_websocket else _websocket_protocol(backend_url)
    socketio_context = None if not backend_is_socketio else await open_robot_backend_socketio(
        backend_url,
        timeout_seconds=args.backend_timeout_seconds,
    )
    websocket_context = None if not backend_is_websocket else await open_robot_backend_websocket(
        backend_url,
        timeout_seconds=args.backend_timeout_seconds,
    )

    if socketio_context is None:
        socketio_client = None
        socketio_manager = None
    else:
        socketio_manager = socketio_context
        socketio_client = await socketio_manager.__aenter__()

    if websocket_context is None:
        websocket = None
        websocket_manager = None
    else:
        websocket_manager = websocket_context
        websocket = await websocket_manager.__aenter__()

    try:
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
            if backend_url:
                if socketio_client is not None:
                    request_id = generate_request_id()
                    backend_response = await post_event_socketio(
                        socketio_client,
                        event,
                        timeout_seconds=args.backend_timeout_seconds,
                        request_id=request_id,
                        function="tracking",
                    )
                elif websocket is not None:
                    request_id = generate_request_id()
                    backend_response = await post_event_ws(
                        websocket,
                        event,
                        timeout_seconds=args.backend_timeout_seconds,
                        on_event=_log_backend_event,
                        request_id=request_id,
                        function="tracking",
                        protocol=str(websocket_protocol),
                    )
                else:
                    backend_response = post_event(
                        backend_url,
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
    finally:
        if socketio_manager is not None:
            await socketio_manager.__aexit__(None, None, None)
        if websocket_manager is not None:
            await websocket_manager.__aexit__(None, None, None)

    return 0


async def _async_main() -> int:
    args = parse_args()
    if args.sample_every <= 0:
        raise ValueError("--sample-every must be positive")
    if args.vid_stride <= 0:
        raise ValueError("--vid-stride must be positive")
    if args.interval_seconds <= 0:
        raise ValueError("--interval-seconds must be positive")
    if args.backend_timeout_seconds <= 0:
        raise ValueError("--backend-timeout-seconds must be positive")
    if args.max_events is not None and args.max_events <= 0:
        raise ValueError("--max-events must be positive when provided")

    output_dir = Path(args.output_dir)
    session_id = args.session_id or generate_session_id()

    _configure_device_runtime(args.device)
    YOLO = _load_yolo()
    model = YOLO(args.model)

    source = normalize_source(args.source)
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

    return await _run_backend_stream(args, result_stream, output_dir, session_id, video_fps)


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    raise SystemExit(main())
