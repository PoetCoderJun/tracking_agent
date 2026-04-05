from __future__ import annotations

import pytest

from backend.perception.stream import RobotDetection
from backend.tracking.benchmark import (
    _ground_truth_subset,
    bbox_iou,
    evaluate_sequence_detections,
    load_sequence_ground_truth,
    select_initial_target_track_id,
)


def test_load_sequence_ground_truth_converts_xywh_to_xyxy(tmp_path) -> None:
    labels_path = tmp_path / "labels.txt"
    labels_path.write_text("0 10 20 30 40\n1 12 22 30 40\n", encoding="utf-8")

    ground_truth = load_sequence_ground_truth(labels_path)

    assert ground_truth == {
        0: [10, 20, 40, 60],
        1: [12, 22, 42, 62],
    }


def test_load_sequence_ground_truth_skips_zero_sized_boxes(tmp_path) -> None:
    labels_path = tmp_path / "labels.txt"
    labels_path.write_text("0 10 20 30 40\n1 0 0 0 0\n2 12 22 30 40\n", encoding="utf-8")

    ground_truth = load_sequence_ground_truth(labels_path)

    assert ground_truth == {
        0: [10, 20, 40, 60],
        2: [12, 22, 42, 62],
    }


def test_ground_truth_subset_keeps_only_processed_frames() -> None:
    subset = _ground_truth_subset(
        {
            0: [10, 20, 40, 60],
            2: [12, 22, 42, 62],
            4: [14, 24, 44, 64],
        },
        allowed_frame_indices=[2, 4],
    )

    assert subset == {
        2: [12, 22, 42, 62],
        4: [14, 24, 44, 64],
    }


def test_select_initial_target_track_id_uses_highest_iou_match() -> None:
    detections = [
        RobotDetection(track_id=3, bbox=[100, 100, 130, 140], score=0.8),
        RobotDetection(track_id=7, bbox=[12, 20, 42, 60], score=0.9),
    ]

    target_track_id, initial_match_iou = select_initial_target_track_id(
        detections,
        [10, 20, 40, 60],
    )

    assert target_track_id == 7
    assert initial_match_iou == pytest.approx(bbox_iou([12, 20, 42, 60], [10, 20, 40, 60]))


def test_evaluate_sequence_detections_scores_bound_track_against_center_distance() -> None:
    result = evaluate_sequence_detections(
        sequence_name="corridor1",
        ground_truth_by_frame={
            0: [10, 10, 30, 30],
            1: [20, 20, 40, 40],
            2: [30, 30, 50, 50],
        },
        detections_by_frame={
            0: [RobotDetection(track_id=7, bbox=[11, 11, 31, 31], score=0.9)],
            1: [RobotDetection(track_id=7, bbox=[21, 21, 41, 41], score=0.9)],
            2: [RobotDetection(track_id=7, bbox=[150, 150, 170, 170], score=0.9)],
        },
        distance_threshold_px=50.0,
    )

    assert result.target_track_id == 7
    assert result.evaluated_frames == 3
    assert result.predicted_frames == 3
    assert result.success_frames == 2
    assert result.success_rate == pytest.approx(2 / 3)


def test_evaluate_sequence_detections_does_not_rebind_after_init_failure() -> None:
    result = evaluate_sequence_detections(
        sequence_name="room",
        ground_truth_by_frame={
            0: [10, 10, 30, 30],
            1: [14, 14, 34, 34],
        },
        detections_by_frame={
            0: [RobotDetection(track_id=9, bbox=[200, 200, 230, 240], score=0.9)],
            1: [RobotDetection(track_id=9, bbox=[14, 14, 34, 34], score=0.9)],
        },
    )

    assert result.target_track_id is None
    assert result.predicted_frames == 0
    assert result.success_frames == 0
    assert result.success_rate == 0.0


def test_evaluate_sequence_detections_respects_frame_step_and_max_frames() -> None:
    result = evaluate_sequence_detections(
        sequence_name="lab_corridor",
        ground_truth_by_frame={
            0: [10, 10, 30, 30],
            1: [11, 11, 31, 31],
            2: [12, 12, 32, 32],
            3: [13, 13, 33, 33],
            4: [14, 14, 34, 34],
        },
        detections_by_frame={
            0: [RobotDetection(track_id=5, bbox=[10, 10, 30, 30], score=0.9)],
            2: [RobotDetection(track_id=5, bbox=[12, 12, 32, 32], score=0.9)],
            4: [RobotDetection(track_id=5, bbox=[14, 14, 34, 34], score=0.9)],
        },
        frame_step=2,
        max_frames=2,
    )

    assert result.evaluated_frames == 2
    assert result.predicted_frames == 2
    assert result.success_frames == 2
    assert result.success_rate == 1.0
