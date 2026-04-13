"""Environment observation adapters and perception helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from world.perception.types import (
    AUDIO_SENSOR_NAME,
    CAMERA_SENSOR_NAME,
    DerivedObservation,
    DerivedWorker,
    IMU_SENSOR_NAME,
    LIDAR_SENSOR_NAME,
    PERSON_DETECTION_KIND,
    RADAR_SENSOR_NAME,
    Observation,
    SensorWorker,
)
from world.perception.recorder import PerceptionRecorder
from world.perception.service import LocalPerceptionService
from world.perception.store import PerceptionStore
from world.perception.stream import (
    RobotDetection,
    RobotFrame,
    RobotIngestEvent,
    append_event_jsonl,
    current_timestamp_ms,
    event_payload,
    generate_request_id,
    generate_session_id,
    is_camera_source,
    normalize_source,
    parse_frame_rate,
    probe_video_fps,
    save_frame_image,
    trim_event_jsonl,
    video_timestamp_seconds,
)


def _normalized_track_id_set(raw_track_ids: Any) -> set[int]:
    normalized: set[int] = set()
    for track_id in list(raw_track_ids or []):
        try:
            normalized.add(int(track_id))
        except (TypeError, ValueError):
            continue
    return normalized


def _normalized_detection(detection: Any, *, excluded_track_ids: set[int]) -> Dict[str, Any] | None:
    if not isinstance(detection, dict):
        return None
    bbox = detection.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    raw_track_id = detection.get("track_id")
    track_id = None if raw_track_id in (None, "") else int(raw_track_id)
    if track_id is not None and track_id in excluded_track_ids:
        return None
    return {
        "track_id": track_id,
        "bbox": [int(value) for value in bbox],
        "score": float(detection.get("score", 1.0)),
        "label": str(detection.get("label", "person")),
    }


def _normalized_frame(
    *,
    frame_id: Any,
    timestamp_ms: Any,
    image_path: Any,
    detections: Any,
    excluded_track_ids: set[int],
) -> Dict[str, Any]:
    normalized_detections: List[Dict[str, Any]] = []
    for detection in list(detections or []):
        normalized = _normalized_detection(detection, excluded_track_ids=excluded_track_ids)
        if normalized is not None:
            normalized_detections.append(normalized)
    return {
        "frame_id": str(frame_id).strip(),
        "timestamp_ms": int(timestamp_ms or 0),
        "image_path": str(image_path or "").strip(),
        "detections": normalized_detections,
    }


def recent_frames(
    *,
    state_root: Path,
    excluded_track_ids: Any = None,
) -> List[Dict[str, Any]]:
    excluded_track_id_set = _normalized_track_id_set(excluded_track_ids)
    frames: List[Dict[str, Any]] = []
    service = LocalPerceptionService(state_root)
    for observation in service.recent_camera_observations():
        payload = dict(observation.get("payload") or {})
        meta = dict(observation.get("meta") or {})
        frame_id = str(payload.get("frame_id", observation.get("id", ""))).strip()
        frames.append(
            _normalized_frame(
                frame_id=frame_id,
                timestamp_ms=observation.get("ts_ms", 0),
                image_path=payload.get("image_path", ""),
                detections=meta.get("detections") or [],
                excluded_track_ids=excluded_track_id_set,
            )
        )
    return frames


@dataclass(frozen=True)
class PerceptionBundle:
    vision: Dict[str, Any]
    system1: Dict[str, Any]
    language: Dict[str, Any]
    memory: Dict[str, Any]
    user_preferences: Dict[str, Any]
    environment_map: Dict[str, Any]


RobotPerceptionBundle = PerceptionBundle


def build_perception_bundle(session) -> PerceptionBundle:
    state_root = Path(session.state_paths["state_root"])
    frames = recent_frames(state_root=state_root)
    latest_frame = None if not frames else frames[-1]
    perception_snapshot = session.perception_snapshot
    return PerceptionBundle(
        vision={
            "latest_frame": latest_frame,
            "recent_frames": frames,
        },
        system1={
            "latest_frame_result": perception_snapshot.get("latest_frame_result"),
            "recent_frame_results": list(perception_snapshot.get("recent_frame_results") or []),
            "stream_status": dict(perception_snapshot.get("stream_status") or {}),
            "model": dict(perception_snapshot.get("model") or {}),
        },
        language={
            "latest_request_function": session.language_context["latest_request_function"],
            "latest_request_id": session.language_context["latest_request_id"],
            "latest_user_text": session.language_context["latest_user_text"],
            "recent_dialogue": session.recent_dialogue(limit=6),
        },
        memory={
            "latest_result": dict(session.session.get("latest_result") or {}) or None,
        },
        user_preferences=dict(session.user_preferences),
        environment_map=dict(session.environment),
    )


__all__ = [
    "AUDIO_SENSOR_NAME",
    "CAMERA_SENSOR_NAME",
    "DerivedObservation",
    "DerivedWorker",
    "IMU_SENSOR_NAME",
    "LIDAR_SENSOR_NAME",
    "LocalPerceptionService",
    "Observation",
    "PERSON_DETECTION_KIND",
    "PerceptionBundle",
    "PerceptionRecorder",
    "PerceptionStore",
    "RADAR_SENSOR_NAME",
    "RobotDetection",
    "RobotFrame",
    "RobotIngestEvent",
    "RobotPerceptionBundle",
    "SensorWorker",
    "append_event_jsonl",
    "build_perception_bundle",
    "current_timestamp_ms",
    "event_payload",
    "generate_request_id",
    "generate_session_id",
    "is_camera_source",
    "normalize_source",
    "recent_frames",
    "parse_frame_rate",
    "probe_video_fps",
    "save_frame_image",
    "trim_event_jsonl",
    "video_timestamp_seconds",
]
