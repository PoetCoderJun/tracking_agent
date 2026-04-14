from __future__ import annotations

import argparse
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from world.perception.service import LocalPerceptionService
from world.perception.stream import (
    RobotFrame,
    RobotIngestEvent,
    current_timestamp_ms,
    generate_request_id,
    probe_video_fps,
    save_frame_image,
    video_timestamp_seconds,
)
from world.perception.stream import RobotDetection
from agent.project_paths import PROJECT_ROOT, resolve_project_path
from agent.runner import run_due_tracking_step
from agent.session import AgentSessionStore
from world.system1 import extract_person_detections, load_yolo
from capabilities.tracking.entrypoints.turns import (
    process_tracking_init_direct,
    process_tracking_request_direct,
)
from capabilities.tracking.runtime.context import tracking_state_snapshot

DEFAULT_DATASET_ROOT = PROJECT_ROOT / "tests" / "dataset"
DEFAULT_MODEL = "yolov8n.pt"
DEFAULT_TRACKER = "bytetrack.yaml"
DEFAULT_DISTANCE_THRESHOLD_PX = 50.0
DEFAULT_TRACKER_FPS = 8.0
DEFAULT_REBIND_AFTER_MISSED_FRAMES = 1
DEFAULT_OBSERVATION_INTERVAL_SECONDS = 1.0
VIDEO_FILENAME = "raw_video.mp4"
LABELS_FILENAME = "labels.txt"


@dataclass(frozen=True)
class BenchmarkSequence:
    name: str
    video_path: Path
    labels_path: Path


@dataclass(frozen=True)
class SequenceBenchmarkResult:
    name: str
    evaluated_frames: int
    predicted_frames: int
    success_frames: int
    success_rate: float
    success_rate_percent: float
    mean_center_distance_px: float | None
    target_track_id: int | None
    initial_match_iou: float
    distance_threshold_px: float
    frame_step: int
    first_labeled_frame: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the tracking benchmark against tests/dataset using the current continuous-tracking runtime path by default."
        )
    )
    parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT), help=argparse.SUPPRESS)
    parser.add_argument(
        "--sequence",
        action="append",
        dest="sequences",
        default=None,
        help="Optional sequence filter. Repeat the flag to run a subset.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=argparse.SUPPRESS)
    parser.add_argument("--tracker", default=DEFAULT_TRACKER, help=argparse.SUPPRESS)
    parser.add_argument("--device", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--conf", type=float, default=0.25, help=argparse.SUPPRESS)
    parser.add_argument("--imgsz", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--person-class-id", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument(
        "--tracker-fps",
        type=float,
        default=DEFAULT_TRACKER_FPS,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--rebind-after-missed-frames",
        type=int,
        default=DEFAULT_REBIND_AFTER_MISSED_FRAMES,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--observation-interval-seconds",
        type=float,
        default=DEFAULT_OBSERVATION_INTERVAL_SECONDS,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--env-file", default=".ENV", help=argparse.SUPPRESS)
    parser.add_argument("--device-id", default="robot_01", help=argparse.SUPPRESS)
    parser.add_argument("--continue-text", default="继续跟踪", help=argparse.SUPPRESS)
    parser.add_argument(
        "--benchmark-run-root",
        default="./.runtime/tracking-benchmark",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--distance-threshold-px",
        type=float,
        default=DEFAULT_DISTANCE_THRESHOLD_PX,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Optional cap per sequence for quick smoke runs.",
    )
    parser.add_argument("--output-json", default="", help="Optional path to save the JSON report.")
    return parser.parse_args(argv)


def parse_label_line(line: str) -> tuple[int, List[int] | None]:
    raw = line.strip()
    if not raw:
        raise ValueError("Label line cannot be empty")
    parts = raw.split()
    if len(parts) != 5:
        raise ValueError(f"Expected 5 fields per label line, got {len(parts)}: {line!r}")
    frame_index, x, y, width, height = [int(value) for value in parts]
    if width <= 0 or height <= 0:
        return frame_index, None
    return frame_index, [x, y, x + width, y + height]


def load_sequence_label_map(labels_path: Path) -> Dict[int, List[int] | None]:
    labels: Dict[int, List[int] | None] = {}
    for line in labels_path.read_text(encoding="utf-8").splitlines():
        frame_index, bbox = parse_label_line(line)
        labels[frame_index] = bbox
    if not labels:
        raise ValueError(f"No labels found in {labels_path}")
    return labels


def discover_benchmark_sequences(
    dataset_root: Path,
    *,
    requested_names: Sequence[str] | None = None,
) -> List[BenchmarkSequence]:
    requested = None if not requested_names else {str(name).strip() for name in requested_names if str(name).strip()}
    sequences: List[BenchmarkSequence] = []
    for child in sorted(dataset_root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if requested is not None and child.name not in requested:
            continue
        video_path = child / VIDEO_FILENAME
        labels_path = child / LABELS_FILENAME
        if not video_path.exists() or not labels_path.exists():
            continue
        sequences.append(
            BenchmarkSequence(
                name=child.name,
                video_path=video_path,
                labels_path=labels_path,
            )
        )
    if not sequences:
        suffix = "" if requested is None else f" for filter {sorted(requested)!r}"
        raise FileNotFoundError(f"No benchmark sequences found under {dataset_root}{suffix}")
    return sequences


def bbox_center_distance_pixels(box_a: Sequence[int], box_b: Sequence[int]) -> float:
    ax = (int(box_a[0]) + int(box_a[2])) / 2.0
    ay = (int(box_a[1]) + int(box_a[3])) / 2.0
    bx = (int(box_b[0]) + int(box_b[2])) / 2.0
    by = (int(box_b[1]) + int(box_b[3])) / 2.0
    return math.hypot(ax - bx, ay - by)


def bbox_iou(box_a: Sequence[int], box_b: Sequence[int]) -> float:
    left = max(int(box_a[0]), int(box_b[0]))
    top = max(int(box_a[1]), int(box_b[1]))
    right = min(int(box_a[2]), int(box_b[2]))
    bottom = min(int(box_a[3]), int(box_b[3]))
    if right <= left or bottom <= top:
        return 0.0
    intersection = float((right - left) * (bottom - top))
    area_a = float((int(box_a[2]) - int(box_a[0])) * (int(box_a[3]) - int(box_a[1])))
    area_b = float((int(box_b[2]) - int(box_b[0])) * (int(box_b[3]) - int(box_b[1])))
    union = area_a + area_b - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def select_initial_target_track_id(
    detections: Sequence[RobotDetection],
    gt_bbox: Sequence[int],
) -> tuple[int | None, float]:
    best_track_id: int | None = None
    best_iou = 0.0
    for detection in detections:
        iou = bbox_iou(detection.bbox, gt_bbox)
        if iou <= best_iou:
            continue
        best_iou = iou
        best_track_id = int(detection.track_id)
    return best_track_id, best_iou


def _first_visible_frame_index(label_map: Mapping[int, Sequence[int] | None]) -> int:
    visible = [int(frame_index) for frame_index, bbox in label_map.items() if bbox is not None]
    if not visible:
        raise ValueError("No visible ground-truth boxes found")
    return min(visible)


def _results_for_video_file_at_target_fps(
    *,
    model: object,
    video_path: Path,
    source_fps: float,
    tracker_fps: float,
    conf: float,
    imgsz: int | None,
    device: str | None,
    tracker: str | None,
    person_class_id: int,
):
    from world.perception.stream import _load_cv2

    if tracker_fps <= 0:
        raise ValueError("tracker_fps must be positive")

    cv2 = _load_cv2()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video source: {video_path}")

    next_sample_at = 0.0
    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp_seconds = video_timestamp_seconds(frame_index + 1, source_fps)
            if timestamp_seconds + 1e-9 < next_sample_at:
                frame_index += 1
                continue

            kwargs: Dict[str, object] = {
                "source": frame,
                "conf": conf,
                "persist": True,
                "stream": False,
                "verbose": False,
                "classes": [person_class_id],
            }
            if imgsz is not None:
                kwargs["imgsz"] = imgsz
            if device not in (None, ""):
                kwargs["device"] = device
            if tracker not in (None, ""):
                kwargs["tracker"] = tracker
            results = model.track(**kwargs)
            yield frame_index, frame, (None if not results else results[0])
            next_sample_at += 1.0 / tracker_fps
            frame_index += 1
    finally:
        capture.release()


def _bound_detection_for_target(
    *,
    detections: Sequence[RobotDetection],
    target_id: int | None,
) -> RobotDetection | None:
    if target_id is None:
        return None
    for detection in detections:
        if int(detection.track_id) == int(target_id):
            return detection
    return None


def _visible_ground_truth_subset_from_label_map(
    *,
    label_map: Mapping[int, Sequence[int] | None],
    allowed_frame_indices: Sequence[int],
) -> Dict[int, List[int]]:
    allowed = {int(frame_index) for frame_index in allowed_frame_indices}
    filtered = {
        int(frame_index): [int(value) for value in bbox]
        for frame_index, bbox in label_map.items()
        if int(frame_index) in allowed and bbox is not None
    }
    if not filtered:
        raise ValueError("No visible ground-truth boxes remain after applying the tracker-frame schedule")
    return filtered


def _evaluate_bound_detections_visible_only(
    *,
    sequence_name: str,
    ground_truth_by_frame: Mapping[int, Sequence[int]],
    detections_by_frame: Mapping[int, Sequence[RobotDetection]],
    distance_threshold_px: float,
) -> SequenceBenchmarkResult:
    predicted_frames = 0
    success_frames = 0
    center_distances: List[float] = []

    for frame_index in sorted(ground_truth_by_frame):
        gt_bbox = list(ground_truth_by_frame[frame_index])
        matching_detection = next(iter(list(detections_by_frame.get(int(frame_index)) or [])), None)
        if matching_detection is None:
            continue
        predicted_frames += 1
        distance = bbox_center_distance_pixels(matching_detection.bbox, gt_bbox)
        center_distances.append(distance)
        if distance < distance_threshold_px:
            success_frames += 1

    evaluated_frames = len(list(ground_truth_by_frame))
    success_rate = 0.0 if evaluated_frames == 0 else success_frames / evaluated_frames
    mean_center_distance = None if not center_distances else sum(center_distances) / len(center_distances)
    first_labeled_frame = min(int(frame_index) for frame_index in ground_truth_by_frame)
    return SequenceBenchmarkResult(
        name=sequence_name,
        evaluated_frames=evaluated_frames,
        predicted_frames=predicted_frames,
        success_frames=success_frames,
        success_rate=success_rate,
        success_rate_percent=success_rate * 100.0,
        mean_center_distance_px=mean_center_distance,
        target_track_id=None,
        initial_match_iou=0.0,
        distance_threshold_px=float(distance_threshold_px),
        frame_step=1,
        first_labeled_frame=first_labeled_frame,
    )


def run_sequence_benchmark(
    *,
    sequence: BenchmarkSequence,
    model_path: Path,
    tracker: str | None,
    device: str | None,
    conf: float,
    imgsz: int | None,
    person_class_id: int,
    distance_threshold_px: float,
    max_frames: int | None,
    env_file: Path,
    device_id: str,
    continue_text: str,
    observation_interval_seconds: float,
    benchmark_run_root: Path,
    tracker_fps: float,
    rebind_after_missed_frames: int,
) -> SequenceBenchmarkResult:
    return run_sequence_benchmark_rebind_fsm(
        sequence=sequence,
        model_path=model_path,
        tracker=tracker,
        device=device,
        conf=conf,
        imgsz=imgsz,
        person_class_id=person_class_id,
        distance_threshold_px=distance_threshold_px,
        max_frames=max_frames,
        env_file=env_file,
        device_id=device_id,
        continue_text=continue_text,
        benchmark_run_root=benchmark_run_root,
        observation_interval_seconds=observation_interval_seconds,
        tracker_fps=tracker_fps,
        rebind_after_missed_frames=rebind_after_missed_frames,
    )


def run_sequence_benchmark_rebind_fsm(
    *,
    sequence: BenchmarkSequence,
    model_path: Path,
    tracker: str | None,
    device: str | None,
    conf: float,
    imgsz: int | None,
    person_class_id: int,
    distance_threshold_px: float,
    max_frames: int | None,
    env_file: Path,
    device_id: str,
    continue_text: str,
    benchmark_run_root: Path,
    observation_interval_seconds: float,
    tracker_fps: float,
    rebind_after_missed_frames: int,
) -> SequenceBenchmarkResult:
    if tracker_fps <= 0:
        raise ValueError("tracker_fps must be positive")
    if observation_interval_seconds <= 0:
        raise ValueError("observation_interval_seconds must be positive")
    if rebind_after_missed_frames <= 0:
        raise ValueError("rebind_after_missed_frames must be positive")
    if max_frames is not None and max_frames <= 0:
        raise ValueError("max_frames must be positive when provided")

    run_root = benchmark_run_root / f"{sequence.name}_rebind_fsm"
    if run_root.exists():
        shutil.rmtree(run_root)
    state_root = run_root / "state"
    artifacts_root = run_root / "artifacts"
    session_id = f"bench_{sequence.name}_rebind_fsm"

    perception_service = LocalPerceptionService(state_root=state_root)
    perception_service.prepare(fresh_state=True)
    sessions = AgentSessionStore(state_root=state_root)

    label_map = load_sequence_label_map(sequence.labels_path)
    first_visible_frame = _first_visible_frame_index(label_map)
    YOLO = load_yolo()
    model = YOLO(str(model_path))
    source_fps = probe_video_fps(sequence.video_path)

    frames_dir = state_root / "perception" / "sessions" / session_id / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    detections_by_frame: Dict[int, List[RobotDetection]] = {}
    processed_frame_indices: List[int] = []
    initialized = False
    trace_entries: List[Dict[str, object]] = []
    next_snapshot_at = 0.0

    result_stream = _results_for_video_file_at_target_fps(
        model=model,
        video_path=sequence.video_path,
        source_fps=source_fps,
        tracker_fps=tracker_fps,
        conf=conf,
        imgsz=imgsz,
        device=device,
        tracker=tracker,
        person_class_id=person_class_id,
    )
    try:
        for event_index, (frame_index, frame_bgr, result) in enumerate(result_stream):
            if frame_index not in label_map:
                continue
            if max_frames is not None and len(processed_frame_indices) >= max_frames:
                break
            timestamp_seconds = video_timestamp_seconds(frame_index + 1, source_fps)
            if timestamp_seconds + 1e-9 < next_snapshot_at:
                continue
            next_snapshot_at += observation_interval_seconds

            frame_id = f"frame_{len(processed_frame_indices):06d}"
            frame_path = frames_dir / f"{frame_id}.jpg"
            save_frame_image(frame_bgr if result is None else result.orig_img, frame_path)
            frame_detections = [] if result is None else extract_person_detections(result, person_class_id=person_class_id)
            perception_service.write_observation(
                RobotIngestEvent(
                    session_id=session_id,
                    device_id=device_id,
                    frame=RobotFrame(
                        frame_id=frame_id,
                        timestamp_ms=current_timestamp_ms(),
                        image_path=str(frame_path),
                    ),
                    detections=frame_detections,
                    text="",
                ),
            )
            processed_frame_indices.append(frame_index)
            gt_bbox = label_map.get(frame_index)

            if not initialized:
                if gt_bbox is None or frame_index < first_visible_frame:
                    detections_by_frame[frame_index] = []
                    trace_entries.append(
                        {
                            "event_index": len(processed_frame_indices) - 1,
                            "raw_frame_index": frame_index,
                            "gt_visible": False,
                            "candidate_track_ids": [int(d.track_id) for d in frame_detections],
                            "current_target_id_before": None,
                            "current_target_id_after": None,
                            "recovery_mode_before": False,
                            "recovery_mode_after": False,
                            "consecutive_missed_before": 0,
                            "consecutive_missed_after": 0,
                            "track_attempted": False,
                            "decision_after": None,
                            "found_after": False,
                            "distance_to_gt_after": None,
                        }
                    )
                    continue
                target_track_id, _ = select_initial_target_track_id(
                    frame_detections,
                    gt_bbox,
                )
                if target_track_id is not None:
                    process_tracking_init_direct(
                        sessions=sessions,
                        session_id=session_id,
                        device_id=device_id,
                        text=f"开始跟踪 ID 为 {target_track_id} 的人。",
                        request_id=generate_request_id(prefix="bench_init"),
                        env_file=env_file,
                        artifacts_root=artifacts_root,
                    )
                    initialized = True

            session = sessions.load(session_id, device_id=device_id)
            tracking_state = tracking_state_snapshot((session.capabilities.get("tracking-init") or {}))
            current_target_id = tracking_state.get("latest_target_id")
            current_target_id_before = current_target_id
            bound_detection = _bound_detection_for_target(
                detections=frame_detections,
                target_id=current_target_id,
            )
            bound_before = bound_detection is not None
            recovery_mode_before = False
            consecutive_missed_before = 0

            review_payload = None
            if initialized:
                review_payload = run_due_tracking_step(
                    sessions=sessions,
                    session_id=session_id,
                    device_id=device_id,
                    env_file=env_file,
                    artifacts_root=artifacts_root,
                    owner_id=f"bench_loop:{session_id}",
                    continue_text=continue_text,
                    interval_seconds=observation_interval_seconds,
                )
                session = sessions.load(session_id, device_id=device_id)
                tracking_state = tracking_state_snapshot((session.capabilities.get("tracking-init") or {}))
                current_target_id = tracking_state.get("latest_target_id")
                bound_detection = _bound_detection_for_target(
                    detections=frame_detections,
                    target_id=current_target_id,
                )

            latest_result = (sessions.load(session_id, device_id=device_id).latest_result or {})
            if bound_detection is not None:
                detections_by_frame[frame_index] = [bound_detection]
            else:
                detections_by_frame[frame_index] = []

            distance_to_gt_after = None
            if gt_bbox is not None and bound_detection is not None:
                distance_to_gt_after = bbox_center_distance_pixels(bound_detection.bbox, gt_bbox)

            trace_entries.append(
                {
                    "event_index": len(processed_frame_indices) - 1,
                    "raw_frame_index": frame_index,
                    "gt_visible": gt_bbox is not None,
                    "gt_bbox": None if gt_bbox is None else [int(value) for value in gt_bbox],
                    "candidate_track_ids": [int(d.track_id) for d in frame_detections],
                    "candidate_bboxes": [
                        {"track_id": int(d.track_id), "bbox": [int(value) for value in d.bbox]}
                        for d in frame_detections
                    ],
                    "current_target_id_before": current_target_id_before,
                    "current_target_id_after": current_target_id,
                    "bound_before": bound_before,
                    "bound_after": bound_detection is not None,
                    "recovery_mode_before": recovery_mode_before,
                    "recovery_mode_after": False,
                    "consecutive_missed_before": consecutive_missed_before,
                    "consecutive_missed_after": 0,
                    "track_attempted": bool(review_payload and review_payload.get("trigger") == "event_rebind"),
                    "review_attempted": bool(review_payload and review_payload.get("trigger") == "cadence_review"),
                    "decision_after": latest_result.get("decision"),
                    "found_after": latest_result.get("found"),
                    "latest_result_target_id": latest_result.get("target_id"),
                    "distance_to_gt_after": distance_to_gt_after,
                    "reason_after": str(latest_result.get("reason", "") or ""),
                    "text_after": str(latest_result.get("text", "") or ""),
                }
            )
    finally:
        close = getattr(result_stream, "close", None)
        if callable(close):
            close()

    (run_root / "recovery_trace.json").write_text(
        json.dumps(trace_entries, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    visible_ground_truth = _visible_ground_truth_subset_from_label_map(
        label_map=label_map,
        allowed_frame_indices=processed_frame_indices,
    )
    return _evaluate_bound_detections_visible_only(
        sequence_name=sequence.name,
        ground_truth_by_frame=visible_ground_truth,
        detections_by_frame=detections_by_frame,
        distance_threshold_px=distance_threshold_px,
    )


def _round_optional(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _sequence_result_payload(result: SequenceBenchmarkResult) -> Dict[str, object]:
    return {
        "name": result.name,
        "evaluated_frames": result.evaluated_frames,
        "predicted_frames": result.predicted_frames,
        "success_frames": result.success_frames,
        "success_rate": round(result.success_rate, 6),
        "success_rate_percent": round(result.success_rate_percent, 2),
        "mean_center_distance_px": _round_optional(result.mean_center_distance_px, 2),
        "target_track_id": result.target_track_id,
        "initial_match_iou": round(result.initial_match_iou, 6),
        "distance_threshold_px": round(result.distance_threshold_px, 2),
        "frame_step": result.frame_step,
        "first_labeled_frame": result.first_labeled_frame,
    }


def benchmark_dataset(
    *,
    dataset_root: Path,
    requested_sequences: Sequence[str] | None,
    model_path: Path,
    tracker: str | None,
    device: str | None,
    conf: float,
    imgsz: int | None,
    person_class_id: int,
    distance_threshold_px: float,
    max_frames: int | None,
    env_file: Path,
    device_id: str,
    continue_text: str,
    observation_interval_seconds: float,
    benchmark_run_root: Path,
    tracker_fps: float,
    rebind_after_missed_frames: int,
) -> Dict[str, object]:
    sequence_results = [
        run_sequence_benchmark(
            sequence=sequence,
            model_path=model_path,
            tracker=tracker,
            device=device,
            conf=conf,
            imgsz=imgsz,
            person_class_id=person_class_id,
            distance_threshold_px=distance_threshold_px,
            max_frames=max_frames,
            env_file=env_file,
            device_id=device_id,
            continue_text=continue_text,
            observation_interval_seconds=observation_interval_seconds,
            benchmark_run_root=benchmark_run_root,
            tracker_fps=tracker_fps,
            rebind_after_missed_frames=rebind_after_missed_frames,
        )
        for sequence in discover_benchmark_sequences(dataset_root, requested_names=requested_sequences)
    ]

    total_evaluated_frames = sum(result.evaluated_frames for result in sequence_results)
    total_success_frames = sum(result.success_frames for result in sequence_results)
    overall_success_rate = 0.0 if total_evaluated_frames == 0 else total_success_frames / total_evaluated_frames
    return {
        "dataset_root": str(dataset_root),
        "model": str(model_path),
        "tracker": None if tracker in (None, "") else str(tracker),
        "device": None if device in (None, "") else str(device),
        "conf": float(conf),
        "imgsz": imgsz,
        "person_class_id": int(person_class_id),
        "protocol": {
            "metric": "sequence_success_rate",
            "distance_threshold_px": round(float(distance_threshold_px), 2),
            "distance_definition": "bbox_center_euclidean_distance",
            "binding_rule": "bind target to the highest-IoU detection on the first labeled frame, then follow the same track_id",
            "paper_alignment_note": (
                "The paper states that success is counted when bbox distance is under 50px. "
                "This benchmark instantiates that distance as center-point Euclidean distance."
            ),
            "missing_gt_note": "Frames whose labels use zero-sized boxes are skipped because there is no visible GT bbox to score.",
            "runtime_alignment_note": (
                "The benchmark reuses the production tracking-init surface and the continuous "
                "runner->tracking loop path, with tracking decisions committed through the "
                "runtime tracking writer."
            ),
        },
        "tracker_fps": round(float(tracker_fps), 3),
        "rebind_after_missed_frames": int(rebind_after_missed_frames),
        "observation_interval_seconds": round(float(observation_interval_seconds), 3),
        "max_frames": max_frames,
        "sequence_results": [_sequence_result_payload(result) for result in sequence_results],
        "summary": {
            "sequence_count": len(sequence_results),
            "evaluated_frames": total_evaluated_frames,
            "success_frames": total_success_frames,
            "overall_success_rate": round(overall_success_rate, 6),
            "overall_success_rate_percent": round(overall_success_rate * 100.0, 2),
        },
    }


def main() -> int:
    args = parse_args()
    if args.tracker_fps <= 0:
        raise ValueError("--tracker-fps must be positive")
    if args.rebind_after_missed_frames <= 0:
        raise ValueError("--rebind-after-missed-frames must be positive")
    if args.observation_interval_seconds <= 0:
        raise ValueError("--observation-interval-seconds must be positive")
    if args.distance_threshold_px <= 0:
        raise ValueError("--distance-threshold-px must be positive")
    if args.max_frames is not None and args.max_frames <= 0:
        raise ValueError("--max-frames must be positive when provided")

    dataset_root = resolve_project_path(args.dataset_root)
    model_path = resolve_project_path(args.model)
    report = benchmark_dataset(
        dataset_root=dataset_root,
        requested_sequences=args.sequences,
        model_path=model_path,
        tracker=str(args.tracker or "").strip() or None,
        device=str(args.device or "").strip() or None,
        conf=float(args.conf),
        imgsz=args.imgsz,
        person_class_id=int(args.person_class_id),
        distance_threshold_px=float(args.distance_threshold_px),
        max_frames=args.max_frames,
        env_file=resolve_project_path(args.env_file),
        device_id=str(args.device_id),
        continue_text=str(args.continue_text),
        observation_interval_seconds=float(args.observation_interval_seconds),
        benchmark_run_root=resolve_project_path(args.benchmark_run_root),
        tracker_fps=float(args.tracker_fps),
        rebind_after_missed_frames=int(args.rebind_after_missed_frames),
    )

    payload = json.dumps(report, indent=2, ensure_ascii=True)
    print(payload)
    output_json = str(args.output_json or "").strip()
    if output_json:
        output_path = resolve_project_path(output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
