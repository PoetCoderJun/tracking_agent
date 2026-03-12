from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class FrameRecord:
    index: int
    timestamp_seconds: float
    path: str


@dataclass(frozen=True)
class FrameManifest:
    video_path: str
    sample_fps: float
    current_frame: str
    frames: List[FrameRecord]
    manifest_path: str


def extract_video_to_frame_queue(
    video_path: Path,
    runtime_dir: Path,
    sample_fps: float = 1.0,
) -> FrameManifest:
    frames_dir = runtime_dir / "frames"
    history_dir = frames_dir / "history"
    manifest_path = frames_dir / "manifest.json"
    current_frame_path = frames_dir / "current.jpg"

    history_dir.mkdir(parents=True, exist_ok=True)

    output_pattern = history_dir / "frame_%06d.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            f"fps={sample_fps}",
            "-q:v",
            "2",
            "-start_number",
            "0",
            str(output_pattern),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    frame_files = sorted(history_dir.glob("frame_*.jpg"))
    if not frame_files:
        raise RuntimeError("No frames were extracted from the input video.")

    shutil.copyfile(frame_files[-1], current_frame_path)

    frames = [
        FrameRecord(
            index=index,
            timestamp_seconds=index / sample_fps,
            path=str(frame_path),
        )
        for index, frame_path in enumerate(frame_files)
    ]

    manifest = FrameManifest(
        video_path=str(video_path),
        sample_fps=sample_fps,
        current_frame=str(current_frame_path),
        frames=frames,
        manifest_path=str(manifest_path),
    )

    payload = {
        "video_path": manifest.video_path,
        "sample_fps": manifest.sample_fps,
        "current_frame": manifest.current_frame,
        "history_frames": [asdict(frame) for frame in manifest.frames],
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    return manifest

