from __future__ import annotations

import base64
import json
import subprocess
import time
import numpy as np
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Union

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
    frame = np.asarray(frame_bgr)
    if frame.ndim == 2:
        frame = np.repeat(frame[:, :, None], 3, axis=2)
    elif frame.ndim != 3:
        raise ValueError(f"Unsupported frame dimensions: {frame.shape}")
    if frame.shape[-1] != 3:
        raise ValueError(f"Unsupported channel count: {frame.shape[-1]}")
    if not np.issubdtype(frame.dtype, np.integer):
        frame_f = frame.astype(np.float32, copy=False)
        finite = frame_f[np.isfinite(frame_f)]
        if finite.size > 0 and finite.max() <= 1.0:
            frame_f = frame_f * 255.0
        frame = np.clip(np.rint(frame_f), 0.0, 255.0).astype(np.uint8)
    else:
        frame = np.clip(frame, 0, 255).astype(np.uint8)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(frame[:, :, ::-1])
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


def append_event_jsonl(path: Path, event: RobotIngestEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event_payload(event), ensure_ascii=True))
        handle.write("\n")


def trim_event_jsonl(path: Path, keep_last_lines: int) -> None:
    if keep_last_lines <= 0:
        raise ValueError("keep_last_lines must be positive")
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    trimmed = lines[-keep_last_lines:]
    path.write_text(
        "\n".join(trimmed) + ("\n" if trimmed else ""),
        encoding="utf-8",
    )
