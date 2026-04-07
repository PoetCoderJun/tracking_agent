from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from backend.perception.stream import save_frame_image


def test_save_frame_image_converts_float_pixels_to_uint8(tmp_path: Path) -> None:
    output = tmp_path / "float_frame.jpg"
    frame = np.array(
        [
            [[0.0, 0.0, 1.0], [0.5, 0.5, 0.5]],
            [[0.25, 0.5, 0.75], [1.0, 1.0, 1.0]],
        ],
        dtype=np.float32,
    )
    save_frame_image(frame, output)
    image = Image.open(output)
    assert image.size == (2, 2)
    channels = np.array(image)
    assert channels.min() >= 0
    assert channels.max() > 180
    assert channels.mean() > 70


def test_save_frame_image_handles_grayscale_like_rgb(tmp_path: Path) -> None:
    output = tmp_path / "gray_frame.jpg"
    save_frame_image(np.array([[0, 64, 128], [192, 255, 127]], dtype=np.uint8), output)
    image = Image.open(output)
    assert image.size == (3, 2)
    assert image.getbands() == ("R", "G", "B")
