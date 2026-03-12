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

from tracking_agent.bbox_visualization import save_bbox_visualization
from tracking_agent.output_validator import denormalize_bbox_from_1000_scale


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a bbox visualization for a frame.")
    parser.add_argument("--image", required=True, help="Path to source image")
    parser.add_argument("--output", required=True, help="Output image path")
    parser.add_argument("--bbox", default=None, help="Optional JSON array: [x1, y1, x2, y2]")
    parser.add_argument("--label", default="", help="Optional visualization label")
    parser.add_argument(
        "--bbox-space",
        choices=("normalized_1000", "pixel"),
        default="normalized_1000",
        help="Interpret bbox as 0..1000 normalized coordinates or pixel coordinates.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bbox = json.loads(args.bbox) if args.bbox else None
    pixel_bbox = bbox
    if bbox is not None and args.bbox_space == "normalized_1000":
        with Image.open(args.image) as image:
            pixel_bbox = denormalize_bbox_from_1000_scale(bbox, image.size)
    image_path = save_bbox_visualization(
        image_path=Path(args.image),
        output_path=Path(args.output),
        bbox=pixel_bbox,
        label=args.label,
    )
    print(
        json.dumps(
            {
                "image_path": str(image_path),
                "pixel_bbox": pixel_bbox,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
