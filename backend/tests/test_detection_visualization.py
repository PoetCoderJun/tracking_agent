from __future__ import annotations

from pathlib import Path

from PIL import Image

from skills.tracking.core.visualization import save_detection_visualization


class _Detection:
    def __init__(self, track_id: int, bbox: list[int]):
        self.track_id = track_id
        self.bbox = bbox


def test_save_detection_visualization_writes_labeled_image(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.jpg"
    output_path = tmp_path / "overlay.jpg"
    Image.new("RGB", (120, 90), color="white").save(image_path, format="JPEG")

    save_detection_visualization(
        image_path=image_path,
        detections=[_Detection(12, [10, 10, 50, 70]), _Detection(15, [60, 12, 100, 72])],
        output_path=output_path,
        highlighted_track_id=15,
    )

    assert output_path.exists()
