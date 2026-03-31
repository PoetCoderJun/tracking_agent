from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PIL import Image


MIN_CROP_WIDTH = 16
MIN_CROP_HEIGHT = 16
HORIZONTAL_PADDING_RATIO = 0.12
TOP_PADDING_RATIO = 0.08
BOTTOM_PADDING_RATIO = 0.12


def _expand_interval(start: int, end: int, limit: int, minimum_size: int) -> tuple[int, int]:
    size = end - start
    if size >= minimum_size:
        return start, end

    target_size = min(limit, minimum_size)
    center = (start + end) / 2
    new_start = max(0, min(limit - target_size, round(center - target_size / 2)))
    new_end = min(limit, new_start + target_size)
    if new_end - new_start < target_size:
        new_start = max(0, new_end - target_size)
    return new_start, new_end


def save_target_crop(
    image_path: Path,
    bbox: Sequence[int],
    output_path: Path,
) -> Path:
    with Image.open(image_path) as image:
        width, height = image.size
        x1, y1, x2, y2 = [int(value) for value in bbox]
        raw_left = max(0, min(width, x1))
        raw_top = max(0, min(height, y1))
        raw_right = max(raw_left + 1, min(width, x2))
        raw_bottom = max(raw_top + 1, min(height, y2))
        box_width = max(1, raw_right - raw_left)
        box_height = max(1, raw_bottom - raw_top)
        horizontal_padding = max(2, round(box_width * HORIZONTAL_PADDING_RATIO))
        top_padding = max(2, round(box_height * TOP_PADDING_RATIO))
        bottom_padding = max(2, round(box_height * BOTTOM_PADDING_RATIO))
        left = max(0, raw_left - horizontal_padding)
        top = max(0, raw_top - top_padding)
        right = min(width, raw_right + horizontal_padding)
        bottom = min(height, raw_bottom + bottom_padding)
        left, right = _expand_interval(left, right, width, MIN_CROP_WIDTH)
        top, bottom = _expand_interval(top, bottom, height, MIN_CROP_HEIGHT)
        crop = image.crop((left, top, right, bottom))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        crop.save(output_path, format="JPEG")
    return output_path
