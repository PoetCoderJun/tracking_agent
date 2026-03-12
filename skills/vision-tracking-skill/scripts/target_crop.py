#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.output_validator import denormalize_bbox_from_1000_scale
from tracking_agent.target_crop import save_target_crop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Save a target crop from a frame and bbox.")
    parser.add_argument("--image", required=True, help="Path to source image")
    parser.add_argument("--bbox", required=True, help="JSON array: [x1, y1, x2, y2]")
    parser.add_argument("--output", required=True, help="Output crop path")
    parser.add_argument(
        "--bbox-space",
        choices=("normalized_1000", "pixel"),
        default="normalized_1000",
        help="Interpret bbox as 0..1000 normalized coordinates or pixel coordinates.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bbox = json.loads(args.bbox)
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError("--bbox must decode to [x1, y1, x2, y2]")
    image_path = Path(args.image)
    pixel_bbox = bbox
    if args.bbox_space == "normalized_1000":
        with Image.open(image_path) as image:
            pixel_bbox = denormalize_bbox_from_1000_scale(bbox, image.size)
    crop_path = save_target_crop(image_path, pixel_bbox, Path(args.output))
    print(
        json.dumps(
            {
                "crop_path": str(crop_path),
                "pixel_bbox": pixel_bbox,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
