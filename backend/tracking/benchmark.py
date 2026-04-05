from __future__ import annotations

import argparse
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Iterable, List, Mapping, Sequence

from agent.session_store import AgentSessionStore
from backend.perception.service import LocalPerceptionService
from backend.perception.stream import (
    RobotFrame,
    RobotIngestEvent,
    current_timestamp_ms,
    generate_request_id,
    probe_video_fps,
    save_frame_image,
    video_timestamp_seconds,
)
from backend.perception.stream import RobotDetection
from backend.project_paths import PROJECT_ROOT, resolve_project_path
from backend.tracking.context import tracking_state_snapshot
from backend.tracking.deterministic import (
    apply_tracking_rewrite_output,
    process_tracking_init_direct,
    process_tracking_request_direct,
)
from backend.tracking.rewrite_memory import execute_rewrite_memory_tool

DEFAULT_DATASET_ROOT = PROJECT_ROOT / "backend" / "tests" / "dataset"
DEFAULT_MODEL = "yolov8n.pt"
DEFAULT_TRACKER = "bytetrack.yaml"
DEFAULT_DISTANCE_THRESHOLD_PX = 50.0
DEFAULT_PIPELINE = "paper_stream"
DEFAULT_TRACKER_FPS = 8.0
DEFAULT_REBIND_AFTER_MISSED_FRAMES = 2
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the local YOLO + ByteTrack tracking stack on backend/tests/dataset "
            "using the paper's sequence success-rate style metric."
        )
    )
    parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
    parser.add_argument(
        "--sequence",
        action="append",
        dest="sequences",
        default=None,
        help="Optional sequence filter. Repeat the flag to run a subset.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--tracker", default=DEFAULT_TRACKER)
    parser.add_argument("--device", default=None)
    parser.add_argument(
        "--pipeline",
        choices=["paper_stream", "project_perception", "stack_chain", "rebind_fsm"],
        default=DEFAULT_PIPELINE,
        help=(
            "paper_stream uses direct streamed YOLO+ByteTrack over the whole video. "
            "project_perception uses scripts/run_tracking_perception.py sampling behavior. "
            "stack_chain runs the project perception cadence plus tracking init/track state transitions. "
            "rebind_fsm runs an 8fps tracking state machine: after N consecutive misses, every new tracker frame triggers rebinding."
        ),
    )
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=None)
    parser.add_argument("--person-class-id", type=int, default=0)
    parser.add_argument(
        "--vid-stride",
        type=int,
        default=1,
        help="Tracking stride used by the project_perception or stack_chain pipelines. Larger means lower inference frequency.",
    )
    parser.add_argument(
        "--tracker-fps",
        type=float,
        default=DEFAULT_TRACKER_FPS,
        help="Tracker-frame sampling rate used by the rebind_fsm pipeline.",
    )
    parser.add_argument(
        "--rebind-after-missed-frames",
        type=int,
        default=DEFAULT_REBIND_AFTER_MISSED_FRAMES,
        help="Enter recovery after this many consecutive tracker-frame misses in rebind_fsm.",
    )
    parser.add_argument(
        "--observation-interval-seconds",
        type=float,
        default=DEFAULT_OBSERVATION_INTERVAL_SECONDS,
        help="Observation emission cadence used by the stack_chain pipeline.",
    )
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--device-id", default="robot_01")
    parser.add_argument("--frame-buffer-size", type=int, default=3)
    parser.add_argument("--continue-text", default="继续跟踪")
    parser.add_argument(
        "--benchmark-run-root",
        default="./.runtime/tracking-benchmark",
        help="Runtime root for stack_chain benchmark state and artifacts.",
    )
    parser.add_argument(
        "--distance-threshold-px",
        type=float,
        default=DEFAULT_DISTANCE_THRESHOLD_PX,
        help="Count a frame as success when predicted-target and GT box centers are closer than this threshold.",
    )
    parser.add_argument(
        "--frame-step",
        type=int,
        default=1,
        help="Evaluate every Nth frame. Use 1 for paper-like per-frame evaluation.",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Optional cap per sequence for quick smoke runs.",
    )
    parser.add_argument("--output-json", default="")
    return parser.parse_args()


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


def load_sequence_ground_truth(labels_path: Path) -> Dict[int, List[int]]:
    ground_truth: Dict[int, List[int]] = {}
    for frame_index, bbox in load_sequence_label_map(labels_path).items():
        if bbox is None:
            continue
        ground_truth[frame_index] = bbox
    if not ground_truth:
        raise ValueError(f"No labels found in {labels_path}")
    return ground_truth


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


def _sampled_frame_indices(
    frame_indices: Iterable[int],
    *,
    start_frame: int,
    frame_step: int,
    max_frames: int | None,
) -> List[int]:
    sampled: List[int] = []
    for frame_index in sorted(frame_indices):
        if frame_index < start_frame:
            continue
        if (frame_index - start_frame) % frame_step != 0:
            continue
        if max_frames is not None and len(sampled) >= max_frames:
            break
        sampled.append(frame_index)
    return sampled


def _is_sampled_frame(
    frame_index: int,
    *,
    start_frame: int,
    frame_step: int,
) -> bool:
    if frame_index < start_frame:
        return False
    return (frame_index - start_frame) % frame_step == 0


def evaluate_sequence_detections(
    *,
    sequence_name: str,
    ground_truth_by_frame: Mapping[int, Sequence[int]],
    detections_by_frame: Mapping[int, Sequence[RobotDetection]],
    distance_threshold_px: float = DEFAULT_DISTANCE_THRESHOLD_PX,
    frame_step: int = 1,
    max_frames: int | None = None,
) -> SequenceBenchmarkResult:
    if frame_step <= 0:
        raise ValueError("frame_step must be positive")
    if distance_threshold_px <= 0:
        raise ValueError("distance_threshold_px must be positive")

    first_labeled_frame = min(int(frame_index) for frame_index in ground_truth_by_frame)
    sampled_frames = _sampled_frame_indices(
        ground_truth_by_frame.keys(),
        start_frame=first_labeled_frame,
        frame_step=frame_step,
        max_frames=max_frames,
    )
    if not sampled_frames:
        raise ValueError(f"No labeled frames selected for sequence {sequence_name!r}")

    initial_gt_bbox = list(ground_truth_by_frame[first_labeled_frame])
    initial_detections = list(detections_by_frame.get(first_labeled_frame) or [])
    target_track_id, initial_match_iou = select_initial_target_track_id(initial_detections, initial_gt_bbox)

    predicted_frames = 0
    success_frames = 0
    center_distances: List[float] = []

    for frame_index in sampled_frames:
        if target_track_id is None:
            continue
        gt_bbox = list(ground_truth_by_frame[frame_index])
        matching_detection = next(
            (
                detection
                for detection in list(detections_by_frame.get(frame_index) or [])
                if int(detection.track_id) == int(target_track_id)
            ),
            None,
        )
        if matching_detection is None:
            continue
        predicted_frames += 1
        distance = bbox_center_distance_pixels(matching_detection.bbox, gt_bbox)
        center_distances.append(distance)
        if distance < distance_threshold_px:
            success_frames += 1

    evaluated_frames = len(sampled_frames)
    success_rate = 0.0 if evaluated_frames == 0 else success_frames / evaluated_frames
    mean_center_distance = None if not center_distances else sum(center_distances) / len(center_distances)
    return SequenceBenchmarkResult(
        name=sequence_name,
        evaluated_frames=evaluated_frames,
        predicted_frames=predicted_frames,
        success_frames=success_frames,
        success_rate=success_rate,
        success_rate_percent=success_rate * 100.0,
        mean_center_distance_px=mean_center_distance,
        target_track_id=target_track_id,
        initial_match_iou=initial_match_iou,
        distance_threshold_px=float(distance_threshold_px),
        frame_step=frame_step,
        first_labeled_frame=first_labeled_frame,
    )


def _build_track_kwargs(
    *,
    source: object,
    conf: float,
    imgsz: int | None,
    device: str | None,
    tracker: str | None,
    person_class_id: int,
    frame_step: int,
) -> Dict[str, object]:
    kwargs: Dict[str, object] = {
        "source": source,
        "conf": conf,
        "persist": True,
        "stream": True,
        "verbose": False,
        "classes": [person_class_id],
    }
    if frame_step > 1:
        kwargs["vid_stride"] = frame_step
    if imgsz is not None:
        kwargs["imgsz"] = imgsz
    if device not in (None, ""):
        kwargs["device"] = device
    if tracker not in (None, ""):
        kwargs["tracker"] = tracker
    return kwargs


def _ground_truth_subset(
    ground_truth_by_frame: Mapping[int, Sequence[int]],
    *,
    allowed_frame_indices: Sequence[int],
) -> Dict[int, List[int]]:
    allowed = {int(frame_index) for frame_index in allowed_frame_indices}
    filtered = {
        int(frame_index): [int(value) for value in bbox]
        for frame_index, bbox in ground_truth_by_frame.items()
        if int(frame_index) in allowed
    }
    if not filtered:
        raise ValueError("No labeled frames remain after applying the project sampling schedule")
    return filtered


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
    from scripts.run_tracking_perception import _load_cv2

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
            yield frame_index, (None if not results else results[0])
            next_sample_at += 1.0 / tracker_fps
            frame_index += 1
    finally:
        capture.release()


def _normalized_tracking_skill_patch(pi_payload: Dict[str, object]) -> Dict[str, object] | None:
    raw = pi_payload.get("skill_state_patch")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("skill_state_patch must be an object or null")
    nested = raw.get("tracking")
    if len(raw) == 1 and isinstance(nested, dict):
        return dict(nested)
    return dict(raw)


def _apply_processed_tracking_payload_without_rewrite(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    pi_payload: Dict[str, object],
) -> Dict[str, object]:
    session_result = pi_payload.get("session_result")
    if not isinstance(session_result, dict):
        raise ValueError("Processed tracking payload is missing session_result")

    sessions.apply_skill_result(session_id, dict(session_result))

    latest_result_patch = pi_payload.get("latest_result_patch")
    if isinstance(latest_result_patch, dict) and latest_result_patch:
        sessions.patch_latest_result(
            session_id=session_id,
            patch=dict(latest_result_patch),
            expected_request_id=session_result.get("request_id"),
            expected_frame_id=session_result.get("frame_id"),
        )

    user_preferences_patch = pi_payload.get("user_preferences_patch")
    if isinstance(user_preferences_patch, dict) and user_preferences_patch:
        sessions.patch_user_preferences(session_id, dict(user_preferences_patch))

    environment_map_patch = pi_payload.get("environment_map_patch")
    if isinstance(environment_map_patch, dict) and environment_map_patch:
        sessions.patch_environment(session_id, dict(environment_map_patch))

    perception_cache_patch = pi_payload.get("perception_cache_patch")
    if isinstance(perception_cache_patch, dict) and perception_cache_patch:
        sessions.patch_perception(session_id, dict(perception_cache_patch))

    skill_state_patch = _normalized_tracking_skill_patch(pi_payload)
    if skill_state_patch:
        sessions.patch_skill_state(
            session_id,
            skill_name="tracking",
            patch=skill_state_patch,
        )

    final_session = sessions.load(session_id)
    return {
        "session_id": session_id,
        "status": "processed",
        "skill_name": "tracking",
        "session_result": dict(session_result),
        "latest_result": final_session.latest_result,
        "session": final_session.session,
    }


def _apply_processed_tracking_payload_with_sync_rewrite(
    *,
    sessions: AgentSessionStore,
    session_id: str,
    pi_payload: Dict[str, object],
    env_file: Path,
) -> Dict[str, object]:
    response = _apply_processed_tracking_payload_without_rewrite(
        sessions=sessions,
        session_id=session_id,
        pi_payload=pi_payload,
    )
    rewrite_memory_input = pi_payload.get("rewrite_memory_input")
    if not isinstance(rewrite_memory_input, dict) or not rewrite_memory_input:
        return response

    session = sessions.load(session_id)
    rewrite_output = execute_rewrite_memory_tool(
        session_file=Path(session.state_paths["session_path"]),
        arguments=dict(rewrite_memory_input),
        env_file=env_file,
    )
    apply_tracking_rewrite_output(
        sessions=sessions,
        session_id=session_id,
        rewrite_output=rewrite_output,
    )
    updated_session = sessions.load(session_id)
    response["rewrite_output"] = rewrite_output
    response["session"] = updated_session.session
    return response


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


def _non_target_track_ids_from_detections(
    *,
    detections: Sequence[RobotDetection],
    target_id: int | None,
) -> set[int]:
    track_ids = {int(detection.track_id) for detection in detections}
    if target_id is not None:
        track_ids.discard(int(target_id))
    return track_ids


def _all_track_ids_from_detections(detections: Sequence[RobotDetection]) -> set[int]:
    return {int(detection.track_id) for detection in detections}


def _sequence_result_from_nullable_gt(
    *,
    sequence_name: str,
    label_map: Mapping[int, Sequence[int] | None],
    detections_by_frame: Mapping[int, Sequence[RobotDetection]],
    evaluated_frame_indices: Sequence[int],
    initial_target_track_id: int | None,
    initial_match_iou: float,
    distance_threshold_px: float,
) -> SequenceBenchmarkResult:
    predicted_frames = 0
    success_frames = 0
    center_distances: List[float] = []

    for frame_index in list(evaluated_frame_indices):
        gt_bbox = label_map.get(int(frame_index))
        matching_detection = next(
            (
                detection
                for detection in list(detections_by_frame.get(int(frame_index)) or [])
            ),
            None,
        )
        if matching_detection is None:
            continue
        predicted_frames += 1
        if gt_bbox is None:
            continue
        distance = bbox_center_distance_pixels(matching_detection.bbox, gt_bbox)
        center_distances.append(distance)
        if distance < distance_threshold_px:
            success_frames += 1

    evaluated_frames = len(list(evaluated_frame_indices))
    success_rate = 0.0 if evaluated_frames == 0 else success_frames / evaluated_frames
    mean_center_distance = None if not center_distances else sum(center_distances) / len(center_distances)
    return SequenceBenchmarkResult(
        name=sequence_name,
        evaluated_frames=evaluated_frames,
        predicted_frames=predicted_frames,
        success_frames=success_frames,
        success_rate=success_rate,
        success_rate_percent=success_rate * 100.0,
        mean_center_distance_px=mean_center_distance,
        target_track_id=initial_target_track_id,
        initial_match_iou=initial_match_iou,
        distance_threshold_px=float(distance_threshold_px),
        frame_step=1,
        first_labeled_frame=_first_visible_frame_index(label_map),
    )


def run_sequence_benchmark(
    *,
    sequence: BenchmarkSequence,
    model_path: Path,
    tracker: str | None,
    device: str | None,
    pipeline: str,
    conf: float,
    imgsz: int | None,
    person_class_id: int,
    distance_threshold_px: float,
    frame_step: int,
    vid_stride: int,
    max_frames: int | None,
    env_file: Path,
    device_id: str,
    frame_buffer_size: int,
    continue_text: str,
    observation_interval_seconds: float,
    benchmark_run_root: Path,
    tracker_fps: float,
    rebind_after_missed_frames: int,
) -> SequenceBenchmarkResult:
    if pipeline == "paper_stream":
        return run_sequence_benchmark_paper_stream(
            sequence=sequence,
            model_path=model_path,
            tracker=tracker,
            device=device,
            conf=conf,
            imgsz=imgsz,
            person_class_id=person_class_id,
            distance_threshold_px=distance_threshold_px,
            frame_step=frame_step,
            max_frames=max_frames,
        )
    if pipeline == "project_perception":
        return run_sequence_benchmark_project_perception(
            sequence=sequence,
            model_path=model_path,
            tracker=tracker,
            device=device,
            conf=conf,
            imgsz=imgsz,
            person_class_id=person_class_id,
            distance_threshold_px=distance_threshold_px,
            vid_stride=vid_stride,
            max_frames=max_frames,
        )
    if pipeline == "stack_chain":
        return run_sequence_benchmark_stack_chain(
            sequence=sequence,
            model_path=model_path,
            tracker=tracker,
            device=device,
            conf=conf,
            imgsz=imgsz,
            person_class_id=person_class_id,
            distance_threshold_px=distance_threshold_px,
            vid_stride=vid_stride,
            max_frames=max_frames,
            env_file=env_file,
            device_id=device_id,
            frame_buffer_size=frame_buffer_size,
            continue_text=continue_text,
            observation_interval_seconds=observation_interval_seconds,
            benchmark_run_root=benchmark_run_root,
        )
    if pipeline == "rebind_fsm":
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
            frame_buffer_size=frame_buffer_size,
            continue_text=continue_text,
            benchmark_run_root=benchmark_run_root,
            tracker_fps=tracker_fps,
            rebind_after_missed_frames=rebind_after_missed_frames,
        )
    raise ValueError(f"Unsupported benchmark pipeline: {pipeline}")


def run_sequence_benchmark_paper_stream(
    *,
    sequence: BenchmarkSequence,
    model_path: Path,
    tracker: str | None,
    device: str | None,
    conf: float,
    imgsz: int | None,
    person_class_id: int,
    distance_threshold_px: float,
    frame_step: int,
    max_frames: int | None,
) -> SequenceBenchmarkResult:
    from scripts.run_tracking_perception import _extract_person_detections, _load_yolo

    if frame_step <= 0:
        raise ValueError("frame_step must be positive")
    if max_frames is not None and max_frames <= 0:
        raise ValueError("max_frames must be positive when provided")

    ground_truth_by_frame = load_sequence_ground_truth(sequence.labels_path)
    first_labeled_frame = min(int(frame_index) for frame_index in ground_truth_by_frame)
    YOLO = _load_yolo()
    model = YOLO(str(model_path))
    detections_by_frame: Dict[int, List[RobotDetection]] = {}
    sampled_frames_seen = 0
    result_stream = model.track(
        **_build_track_kwargs(
            source=str(sequence.video_path),
            conf=conf,
            imgsz=imgsz,
            device=device,
            tracker=tracker,
            person_class_id=person_class_id,
            frame_step=frame_step,
        )
    )
    try:
        for sampled_index, result in enumerate(result_stream):
            frame_index = sampled_index * frame_step
            if frame_index < first_labeled_frame:
                continue
            if frame_index not in ground_truth_by_frame or not _is_sampled_frame(
                frame_index,
                start_frame=first_labeled_frame,
                frame_step=frame_step,
            ):
                continue
            detections_by_frame[frame_index] = (
                []
                if result is None
                else _extract_person_detections(result, person_class_id=person_class_id)
            )
            sampled_frames_seen += 1
            if max_frames is not None and sampled_frames_seen >= max_frames:
                break
    finally:
        close = getattr(result_stream, "close", None)
        if callable(close):
            close()

    return evaluate_sequence_detections(
        sequence_name=sequence.name,
        ground_truth_by_frame=ground_truth_by_frame,
        detections_by_frame=detections_by_frame,
        distance_threshold_px=distance_threshold_px,
        frame_step=frame_step,
        max_frames=max_frames,
    )


def run_sequence_benchmark_project_perception(
    *,
    sequence: BenchmarkSequence,
    model_path: Path,
    tracker: str | None,
    device: str | None,
    conf: float,
    imgsz: int | None,
    person_class_id: int,
    distance_threshold_px: float,
    vid_stride: int,
    max_frames: int | None,
) -> SequenceBenchmarkResult:
    from backend.perception.stream import probe_video_fps
    from scripts.run_tracking_perception import _extract_person_detections, _load_yolo, _results_for_video_file

    if vid_stride <= 0:
        raise ValueError("vid_stride must be positive")
    if max_frames is not None and max_frames <= 0:
        raise ValueError("max_frames must be positive when provided")

    ground_truth_by_frame = load_sequence_ground_truth(sequence.labels_path)
    YOLO = _load_yolo()
    model = YOLO(str(model_path))
    fps = probe_video_fps(sequence.video_path)
    args = SimpleNamespace(
        conf=conf,
        imgsz=imgsz,
        device=device,
        tracker=tracker,
        person_class_id=person_class_id,
        vid_stride=vid_stride,
    )

    detections_by_frame: Dict[int, List[RobotDetection]] = {}
    processed_frame_indices: List[int] = []
    result_stream = _results_for_video_file(
        model=model,
        video_path=sequence.video_path,
        fps=fps,
        args=args,
    )
    try:
        for frame_number, result in result_stream:
            frame_index = int(frame_number) - 1
            if frame_index not in ground_truth_by_frame:
                continue
            detections_by_frame[frame_index] = (
                []
                if result is None
                else _extract_person_detections(result, person_class_id=person_class_id)
            )
            processed_frame_indices.append(frame_index)
            if max_frames is not None and len(processed_frame_indices) >= max_frames:
                break
    finally:
        close = getattr(result_stream, "close", None)
        if callable(close):
            close()

    sampled_ground_truth = _ground_truth_subset(
        ground_truth_by_frame,
        allowed_frame_indices=processed_frame_indices,
    )
    return evaluate_sequence_detections(
        sequence_name=sequence.name,
        ground_truth_by_frame=sampled_ground_truth,
        detections_by_frame=detections_by_frame,
        distance_threshold_px=distance_threshold_px,
        frame_step=1,
        max_frames=None,
    )


def run_sequence_benchmark_stack_chain(
    *,
    sequence: BenchmarkSequence,
    model_path: Path,
    tracker: str | None,
    device: str | None,
    conf: float,
    imgsz: int | None,
    person_class_id: int,
    distance_threshold_px: float,
    vid_stride: int,
    max_frames: int | None,
    env_file: Path,
    device_id: str,
    frame_buffer_size: int,
    continue_text: str,
    observation_interval_seconds: float,
    benchmark_run_root: Path,
) -> SequenceBenchmarkResult:
    from scripts.run_tracking_perception import _extract_person_detections, _load_yolo, _results_for_video_file

    if vid_stride <= 0:
        raise ValueError("vid_stride must be positive")
    if observation_interval_seconds <= 0:
        raise ValueError("observation_interval_seconds must be positive")
    if max_frames is not None and max_frames <= 0:
        raise ValueError("max_frames must be positive when provided")

    run_root = benchmark_run_root / f"{sequence.name}_stack_chain_vid{vid_stride}"
    if run_root.exists():
        shutil.rmtree(run_root)
    state_root = run_root / "state"
    artifacts_root = run_root / "artifacts"
    session_id = f"bench_{sequence.name}_stack_vid{vid_stride}"

    perception_service = LocalPerceptionService(state_root=state_root)
    perception_service.prepare_session(
        session_id=session_id,
        device_id=device_id,
        fresh_session=True,
        mark_active=True,
    )
    sessions = AgentSessionStore(state_root=state_root, frame_buffer_size=frame_buffer_size)

    ground_truth_by_frame = load_sequence_ground_truth(sequence.labels_path)
    YOLO = _load_yolo()
    model = YOLO(str(model_path))
    fps = probe_video_fps(sequence.video_path)
    args = SimpleNamespace(
        conf=conf,
        imgsz=imgsz,
        device=device,
        tracker=tracker,
        person_class_id=person_class_id,
        vid_stride=vid_stride,
    )

    frames_dir = state_root / "perception" / "sessions" / session_id / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    detections_by_frame: Dict[int, List[RobotDetection]] = {}
    processed_frame_indices: List[int] = []
    excluded_track_ids: set[int] = set()
    next_video_emit_at = 0.0
    initialized = False

    result_stream = _results_for_video_file(
        model=model,
        video_path=sequence.video_path,
        fps=fps,
        args=args,
    )
    try:
        for emitted_index, (frame_number, result) in enumerate(result_stream):
            frame_index = int(frame_number) - 1
            if frame_index not in ground_truth_by_frame:
                continue
            if max_frames is not None and len(processed_frame_indices) >= max_frames:
                break
            if video_timestamp_seconds(int(frame_number), fps) < next_video_emit_at:
                continue
            next_video_emit_at += observation_interval_seconds

            frame_id = f"frame_{len(processed_frame_indices):06d}"
            frame_path = frames_dir / f"{frame_id}.jpg"
            save_frame_image(result.orig_img, frame_path)
            frame_detections = _extract_person_detections(result, person_class_id=person_class_id)
            event = RobotIngestEvent(
                session_id=session_id,
                device_id=device_id,
                frame=RobotFrame(
                    frame_id=frame_id,
                    timestamp_ms=current_timestamp_ms(),
                    image_path=str(frame_path),
                ),
                detections=frame_detections,
                text="",
            )
            perception_service.write_observation(
                event,
                request_function="observation",
            )
            processed_frame_indices.append(frame_index)

            if not initialized:
                target_track_id, _ = select_initial_target_track_id(
                    frame_detections,
                    ground_truth_by_frame[frame_index],
                )
                if target_track_id is None:
                    detections_by_frame[frame_index] = []
                    continue
                process_tracking_init_direct(
                    sessions=sessions,
                    session_id=session_id,
                    device_id=device_id,
                    text=f"跟踪{target_track_id}号目标",
                    request_id=generate_request_id(prefix="stack_init"),
                    env_file=env_file,
                    artifacts_root=artifacts_root,
                    apply_processed_payload=lambda *, session_id, pi_payload, env_file: _apply_processed_tracking_payload_without_rewrite(
                        sessions=sessions,
                        session_id=session_id,
                        pi_payload=pi_payload,
                    ),
                )
                initialized = True
            else:
                session = sessions.load(session_id, device_id=device_id)
                tracking_state = tracking_state_snapshot((session.skills.get("tracking") or {}))
                target_id = tracking_state.get("latest_target_id")
                bound_detection = _bound_detection_for_target(
                    detections=frame_detections,
                    target_id=target_id,
                )
                if bound_detection is None:
                    process_tracking_request_direct(
                        sessions=sessions,
                        session_id=session_id,
                        device_id=device_id,
                        text=continue_text,
                        request_id=generate_request_id(prefix="stack_track"),
                        env_file=env_file,
                        artifacts_root=artifacts_root,
                        excluded_track_ids=sorted(excluded_track_ids),
                        apply_processed_payload=lambda *, session_id, pi_payload, env_file: _apply_processed_tracking_payload_without_rewrite(
                            sessions=sessions,
                            session_id=session_id,
                            pi_payload=pi_payload,
                        ),
                    )

            session = sessions.load(session_id, device_id=device_id)
            tracking_state = tracking_state_snapshot((session.skills.get("tracking") or {}))
            target_id = tracking_state.get("latest_target_id")
            selected_detection = _bound_detection_for_target(
                detections=frame_detections,
                target_id=target_id,
            )
            detections_by_frame[frame_index] = [] if selected_detection is None else [selected_detection]
            excluded_track_ids.update(
                _non_target_track_ids_from_detections(
                    detections=frame_detections,
                    target_id=target_id,
                )
            )
    finally:
        close = getattr(result_stream, "close", None)
        if callable(close):
            close()

    sampled_ground_truth = _ground_truth_subset(
        ground_truth_by_frame,
        allowed_frame_indices=processed_frame_indices,
    )
    return evaluate_sequence_detections(
        sequence_name=sequence.name,
        ground_truth_by_frame=sampled_ground_truth,
        detections_by_frame=detections_by_frame,
        distance_threshold_px=distance_threshold_px,
        frame_step=1,
        max_frames=None,
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
    frame_buffer_size: int,
    continue_text: str,
    benchmark_run_root: Path,
    tracker_fps: float,
    rebind_after_missed_frames: int,
) -> SequenceBenchmarkResult:
    from scripts.run_tracking_perception import _extract_person_detections, _load_yolo

    if tracker_fps <= 0:
        raise ValueError("tracker_fps must be positive")
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
    perception_service.prepare_session(
        session_id=session_id,
        device_id=device_id,
        fresh_session=True,
        mark_active=True,
    )
    sessions = AgentSessionStore(state_root=state_root, frame_buffer_size=frame_buffer_size)

    label_map = load_sequence_label_map(sequence.labels_path)
    first_visible_frame = _first_visible_frame_index(label_map)
    YOLO = _load_yolo()
    model = YOLO(str(model_path))
    source_fps = probe_video_fps(sequence.video_path)

    frames_dir = state_root / "perception" / "sessions" / session_id / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    detections_by_frame: Dict[int, List[RobotDetection]] = {}
    processed_frame_indices: List[int] = []
    excluded_track_ids: set[int] = set()
    initialized = False
    recovery_mode = False
    consecutive_missed_frames = 0
    initial_target_track_id: int | None = None
    initial_match_iou = 0.0

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
        for event_index, (frame_index, result) in enumerate(result_stream):
            if frame_index not in label_map:
                continue
            if max_frames is not None and len(processed_frame_indices) >= max_frames:
                break

            frame_id = f"frame_{len(processed_frame_indices):06d}"
            frame_path = frames_dir / f"{frame_id}.jpg"
            if result is None:
                break
            save_frame_image(result.orig_img, frame_path)
            frame_detections = _extract_person_detections(result, person_class_id=person_class_id)
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
                request_function="observation",
            )
            processed_frame_indices.append(frame_index)

            if not initialized:
                gt_bbox = label_map.get(frame_index)
                if gt_bbox is None or frame_index < first_visible_frame:
                    detections_by_frame[frame_index] = []
                    continue
                target_track_id, _ = select_initial_target_track_id(
                    frame_detections,
                    gt_bbox,
                )
                if target_track_id is not None:
                    initial_target_track_id = int(target_track_id)
                    initial_match_iou = bbox_iou(
                        next(
                            detection.bbox
                            for detection in frame_detections
                            if int(detection.track_id) == int(target_track_id)
                        ),
                        gt_bbox,
                    )
                    process_tracking_init_direct(
                        sessions=sessions,
                        session_id=session_id,
                        device_id=device_id,
                        text=f"开始跟踪 ID 为 {target_track_id} 的人。",
                        request_id=generate_request_id(prefix="bench_init"),
                        env_file=env_file,
                        artifacts_root=artifacts_root,
                        apply_processed_payload=lambda *, session_id, pi_payload, env_file: _apply_processed_tracking_payload_with_sync_rewrite(
                            sessions=sessions,
                            session_id=session_id,
                            pi_payload=pi_payload,
                            env_file=env_file,
                        ),
                    )
                    initialized = True

            session = sessions.load(session_id, device_id=device_id)
            tracking_state = tracking_state_snapshot((session.skills.get("tracking") or {}))
            current_target_id = tracking_state.get("latest_target_id")
            bound_detection = _bound_detection_for_target(
                detections=frame_detections,
                target_id=current_target_id,
            )

            track_attempted = False
            if initialized:
                if recovery_mode:
                    if bound_detection is not None:
                        recovery_mode = False
                        consecutive_missed_frames = 0
                    else:
                        track_attempted = True
                else:
                    if bound_detection is not None:
                        consecutive_missed_frames = 0
                    else:
                        consecutive_missed_frames += 1
                        if consecutive_missed_frames >= rebind_after_missed_frames:
                            recovery_mode = True
                            track_attempted = True

                if track_attempted:
                    process_tracking_request_direct(
                        sessions=sessions,
                        session_id=session_id,
                        device_id=device_id,
                        text=continue_text,
                        request_id=generate_request_id(prefix="bench_track"),
                        env_file=env_file,
                        artifacts_root=artifacts_root,
                        excluded_track_ids=sorted(excluded_track_ids),
                        append_chat_request=False,
                        apply_processed_payload=lambda *, session_id, pi_payload, env_file: _apply_processed_tracking_payload_with_sync_rewrite(
                            sessions=sessions,
                            session_id=session_id,
                            pi_payload=pi_payload,
                            env_file=env_file,
                        ),
                    )
                    session = sessions.load(session_id, device_id=device_id)
                    tracking_state = tracking_state_snapshot((session.skills.get("tracking") or {}))
                    current_target_id = tracking_state.get("latest_target_id")
                    bound_detection = _bound_detection_for_target(
                        detections=frame_detections,
                        target_id=current_target_id,
                    )
                    if bound_detection is not None:
                        recovery_mode = False
                        consecutive_missed_frames = 0

            if bound_detection is not None:
                detections_by_frame[frame_index] = [bound_detection]
                excluded_track_ids.update(
                    _non_target_track_ids_from_detections(
                        detections=frame_detections,
                        target_id=current_target_id,
                    )
                )
            else:
                detections_by_frame[frame_index] = []
                if track_attempted:
                    excluded_track_ids.update(_all_track_ids_from_detections(frame_detections))
    finally:
        close = getattr(result_stream, "close", None)
        if callable(close):
            close()

    return _sequence_result_from_nullable_gt(
        sequence_name=sequence.name,
        label_map=label_map,
        detections_by_frame=detections_by_frame,
        evaluated_frame_indices=processed_frame_indices,
        initial_target_track_id=initial_target_track_id,
        initial_match_iou=initial_match_iou,
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
    pipeline: str,
    conf: float,
    imgsz: int | None,
    person_class_id: int,
    distance_threshold_px: float,
    frame_step: int,
    vid_stride: int,
    max_frames: int | None,
    env_file: Path,
    device_id: str,
    frame_buffer_size: int,
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
            pipeline=pipeline,
            conf=conf,
            imgsz=imgsz,
            person_class_id=person_class_id,
            distance_threshold_px=distance_threshold_px,
            frame_step=frame_step,
            vid_stride=vid_stride,
            max_frames=max_frames,
            env_file=env_file,
            device_id=device_id,
            frame_buffer_size=frame_buffer_size,
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
        "pipeline": str(pipeline),
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
            "pipeline_note": (
                "project_perception evaluates only frames actually processed by scripts/run_tracking_perception.py. "
                "paper_stream evaluates the whole sampled video stream directly. "
                "rebind_fsm evaluates all tracker frames at tracker_fps and enters recovery after rebind_after_missed_frames consecutive misses."
            ),
        },
        "frame_step": int(frame_step),
        "vid_stride": int(vid_stride),
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
    if args.frame_step <= 0:
        raise ValueError("--frame-step must be positive")
    if args.vid_stride <= 0:
        raise ValueError("--vid-stride must be positive")
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
        pipeline=str(args.pipeline),
        conf=float(args.conf),
        imgsz=args.imgsz,
        person_class_id=int(args.person_class_id),
        distance_threshold_px=float(args.distance_threshold_px),
        frame_step=int(args.frame_step),
        vid_stride=int(args.vid_stride),
        max_frames=args.max_frames,
        env_file=resolve_project_path(args.env_file),
        device_id=str(args.device_id),
        frame_buffer_size=int(args.frame_buffer_size),
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
