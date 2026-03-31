"""Environment observation adapters and perception helpers."""

from backend.perception.interfaces import DerivedWorker, SensorWorker
from backend.perception.models import (
    AUDIO_SENSOR_NAME,
    CAMERA_SENSOR_NAME,
    IMU_SENSOR_NAME,
    LIDAR_SENSOR_NAME,
    PERSON_DETECTION_KIND,
    RADAR_SENSOR_NAME,
    DerivedObservation,
    Observation,
)
from backend.perception.bundle import PerceptionBundle, RobotPerceptionBundle, build_perception_bundle
from backend.perception.recorder import PerceptionRecorder
from backend.perception.service import LocalPerceptionService
from backend.perception.store import PerceptionStore
from backend.perception.stream import (
    RobotDetection,
    RobotFrame,
    RobotIngestEvent,
    append_event_jsonl,
    event_payload,
    is_camera_source,
    normalize_source,
    parse_frame_rate,
    probe_video_fps,
    current_timestamp_ms,
    generate_request_id,
    generate_session_id,
    save_frame_image,
    trim_event_jsonl,
    video_timestamp_seconds,
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
    "parse_frame_rate",
    "probe_video_fps",
    "save_frame_image",
    "trim_event_jsonl",
    "video_timestamp_seconds",
]
