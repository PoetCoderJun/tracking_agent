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

from tracking_agent.output_validator import (
    denormalize_bbox_from_1000_scale,
    validate_locate_result,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a locate-result JSON file.")
    parser.add_argument("result_path", help="Path to a JSON file with a locate result")
    parser.add_argument(
        "--image",
        default=None,
        help="Optional image path used to denormalize bbox from 0..1000 to pixels.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(Path(args.result_path).read_text(encoding="utf-8"))
    normalized = validate_locate_result(payload)
    if args.image and normalized.get("bbox") is not None:
        with Image.open(args.image) as image:
            normalized["pixel_bbox"] = denormalize_bbox_from_1000_scale(
                normalized["bbox"],
                image.size,
            )
    print(json.dumps(normalized, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
