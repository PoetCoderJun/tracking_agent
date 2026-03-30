from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from PIL import Image, ImageDraw


FOUND_COLOR = (46, 204, 113)
MISSING_COLOR = (241, 196, 15)
TEXT_COLOR = (18, 18, 18)


def _clamp_bbox(
    bbox: Sequence[int],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    width, height = image_size
    x1, y1, x2, y2 = [int(value) for value in bbox]
    left = max(0, min(width - 1, x1))
    top = max(0, min(height - 1, y1))
    right = max(left + 1, min(width, x2))
    bottom = max(top + 1, min(height, y2))
    return left, top, right, bottom


def _draw_status_chip(
    draw: ImageDraw.ImageDraw,
    label: str,
    color: tuple[int, int, int],
) -> None:
    text_width = max(48, int(len(label) * 7 + 12))
    text_height = 18
    draw.rectangle((8, 8, 8 + text_width, 8 + text_height), fill=color)
    draw.text((14, 11), label, fill=TEXT_COLOR)


def save_bbox_visualization(
    image_path: Path,
    output_path: Path,
    bbox: Optional[Sequence[int]],
    label: str,
) -> Path:
    with Image.open(image_path) as image:
        canvas = image.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        if bbox is not None:
            left, top, right, bottom = _clamp_bbox(bbox, canvas.size)
            line_width = max(2, round(min(canvas.size) / 180))
            draw.rectangle(
                (left, top, right - 1, bottom - 1),
                outline=FOUND_COLOR,
                width=line_width,
            )
            _draw_status_chip(draw, label, FOUND_COLOR)
        else:
            _draw_status_chip(draw, label, MISSING_COLOR)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, format="JPEG")
    return output_path
