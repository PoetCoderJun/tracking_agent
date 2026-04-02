from __future__ import annotations

from pathlib import Path

from PIL import Image

from skills.tracking.core.validator import denormalize_bbox_from_1000_scale
from skills.tracking.core.crop import save_target_crop


def test_save_target_crop_expands_tiny_bbox_to_minimum_size(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.jpg"
    crop_path = tmp_path / "crop.jpg"
    Image.new("RGB", (100, 80), color="white").save(image_path, format="JPEG")

    save_target_crop(
        image_path=image_path,
        bbox=[50, 20, 51, 68],
        output_path=crop_path,
    )

    with Image.open(crop_path) as crop:
        assert crop.size[0] >= 16
        assert crop.size[1] >= 16


def test_denormalize_bbox_from_1000_scale_maps_to_pixel_coordinates() -> None:
    bbox = denormalize_bbox_from_1000_scale(
        [379, 180, 596, 994],
        image_size=(512, 384),
    )

    assert bbox == [194, 69, 305, 382]
