#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.pipeline import load_frame_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read and summarize a frame manifest.")
    parser.add_argument("manifest", help="Path to frames/manifest.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = load_frame_manifest(Path(args.manifest))
    summary = {
        "video_path": payload.get("video_path"),
        "sample_fps": payload.get("sample_fps"),
        "current_frame": payload.get("current_frame"),
        "history_count": len(payload.get("history_frames", [])),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
