from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Protocol, Sequence

from PIL import Image, ImageDraw


class DetectionLike(Protocol):
    track_id: int
    bbox: Sequence[int]


CANDIDATE_COLOR = (27, 84, 163)
TARGET_COLOR = (216, 76, 47)
TEXT_COLOR = (255, 255, 255)


def _clamp_bbox(bbox: Sequence[int], image_size: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = image_size
    x1, y1, x2, y2 = [int(value) for value in bbox]
    left = max(0, min(width - 1, x1))
    top = max(0, min(height - 1, y1))
    right = max(left + 1, min(width, x2))
    bottom = max(top + 1, min(height, y2))
    return left, top, right, bottom


def save_detection_visualization(
    image_path: Path,
    detections: Iterable[DetectionLike],
    output_path: Path,
    highlighted_track_id: Optional[int] = None,
) -> Path:
    with Image.open(image_path) as image:
        canvas = image.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        line_width = max(2, round(min(canvas.size) / 180))

        for detection in detections:
            left, top, right, bottom = _clamp_bbox(detection.bbox, canvas.size)
            is_target = (
                highlighted_track_id is not None
                and int(detection.track_id) == int(highlighted_track_id)
            )
            color = TARGET_COLOR if is_target else CANDIDATE_COLOR
            label = f"ID {int(detection.track_id)}"
            chip_width = max(52, int(len(label) * 8 + 12))
            chip_height = 20

            draw.rectangle(
                (left, top, right - 1, bottom - 1),
                outline=color,
                width=line_width,
            )
            chip_top = max(0, top - chip_height - 4)
            draw.rectangle(
                (left, chip_top, left + chip_width, chip_top + chip_height),
                fill=color,
            )
            draw.text((left + 6, chip_top + 3), label, fill=TEXT_COLOR)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, format="JPEG")
    return output_path
