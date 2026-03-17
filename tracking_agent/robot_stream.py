from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Union
from urllib.parse import urlsplit

from PIL import Image


SourceValue = Union[int, str]


@dataclass(frozen=True)
class RobotDetection:
    track_id: int
    bbox: List[int]
    score: float
    label: str = "person"


@dataclass(frozen=True)
class RobotFrame:
    frame_id: str
    timestamp_ms: int
    image_path: str


@dataclass(frozen=True)
class RobotIngestEvent:
    session_id: str
    device_id: str
    frame: RobotFrame
    detections: List[RobotDetection]
    text: str


def normalize_source(source: str) -> SourceValue:
    stripped = source.strip()
    if stripped.isdigit():
        return int(stripped)
    return stripped


def generate_session_id(prefix: str = "session") -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}_{timestamp}"


def generate_request_id(prefix: str = "req") -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}_{timestamp}"


def is_camera_source(source: SourceValue) -> bool:
    return isinstance(source, int)


def parse_frame_rate(value: str) -> float:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Frame rate cannot be empty")
    fps = float(Fraction(cleaned)) if "/" in cleaned else float(cleaned)
    if fps <= 0:
        raise ValueError(f"Frame rate must be positive, got {value!r}")
    return fps


def probe_video_fps(video_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate,r_frame_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        try:
            return parse_frame_rate(cleaned)
        except ValueError:
            continue
    raise RuntimeError(f"Unable to determine FPS for video source: {video_path}")


def video_timestamp_seconds(frame_index: int, fps: float) -> float:
    if frame_index <= 0:
        raise ValueError("frame_index must be positive")
    if fps <= 0:
        raise ValueError("fps must be positive")
    return (frame_index - 1) / fps


def current_timestamp_ms() -> int:
    return round(time.time() * 1000)


def save_frame_image(frame_bgr: Any, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(frame_bgr[:, :, ::-1])
    image.save(output_path, format="JPEG")
    return output_path


def event_payload(
    event: RobotIngestEvent,
    include_image_base64: bool = False,
) -> Dict[str, Any]:
    payload = asdict(event)
    if include_image_base64:
        image_bytes = Path(event.frame.image_path).read_bytes()
        payload["frame"]["image_base64"] = base64.b64encode(image_bytes).decode("ascii")
    return payload


def robot_agent_request_payload(
    event: RobotIngestEvent,
    *,
    request_id: str,
    function: str = "tracking",
) -> Dict[str, Any]:
    normalized_function = function.strip().lower()
    payload: Dict[str, Any] = {
        "request_id": request_id.strip(),
        "session_id": event.session_id,
        "function": normalized_function,
        "text": event.text,
    }
    if normalized_function == "tracking":
        image_bytes = Path(event.frame.image_path).read_bytes()
        payload.update(
            {
                "frame_id": event.frame.frame_id,
                "timestamp_ms": event.frame.timestamp_ms,
                "device_id": event.device_id,
                "image_base64": base64.b64encode(image_bytes).decode("ascii"),
                "detections": [asdict(detection) for detection in event.detections],
            }
        )
    return payload


def append_event_jsonl(path: Path, event: RobotIngestEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event_payload(event), ensure_ascii=True))
        handle.write("\n")


def is_websocket_url(url: str) -> bool:
    return urlsplit(url).scheme.lower() in {"ws", "wss"}


def _load_websocket_connect():
    try:
        from websockets.client import connect
    except ImportError as exc:
        raise RuntimeError(
            "Missing websocket client dependency. Install the 'websockets' package before running robot streaming."
        ) from exc
    return connect


def post_event(
    url: str,
    event: RobotIngestEvent,
    timeout_seconds: float = 300,
) -> Dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    payload = event_payload(event, include_image_base64=True)
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
    return {
        "status": getattr(response, "status", 200),
        "body": body,
    }


async def post_event_ws(
    websocket: Any,
    event: RobotIngestEvent,
    timeout_seconds: float = 300,
    on_event: Any = None,
    *,
    request_id: str | None = None,
    function: str = "tracking",
    protocol: str = "robot_ingest",
) -> Dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if protocol == "robot_agent":
        if not request_id:
            raise ValueError("request_id is required when protocol='robot_agent'")
        payload = robot_agent_request_payload(
            event,
            request_id=request_id,
            function=function,
        )
    else:
        payload = event_payload(event, include_image_base64=True)
    await asyncio.wait_for(websocket.send(json.dumps(payload, ensure_ascii=False)), timeout=timeout_seconds)
    while True:
        message = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
        response = json.loads(message)
        if callable(on_event):
            on_event(response)
        if protocol == "robot_agent":
            if response.get("error"):
                raise RuntimeError(str(response.get("error")))
            return {
                "status": int(response.get("status", 200)),
                "body": json.dumps(response, ensure_ascii=True),
            }
        if response.get("type") == "robot_ingest_error":
            raise RuntimeError(str(response.get("error", "Robot ingest websocket request failed")))
        if response.get("type") != "robot_ingest_result":
            continue
        return {
            "status": int(response.get("status", 200)),
            "body": json.dumps(response.get("payload", {}), ensure_ascii=True),
        }


async def open_robot_backend_websocket(
    url: str,
    timeout_seconds: float = 300,
):
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    connect = _load_websocket_connect()
    return connect(
        url,
        open_timeout=timeout_seconds,
        close_timeout=min(timeout_seconds, 10.0),
        ping_interval=20,
        ping_timeout=timeout_seconds,
        max_size=None,
    )
