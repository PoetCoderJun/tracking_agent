"""Environment observation adapters and perception helpers."""

from backend.perception.bundle import PerceptionBundle, RobotPerceptionBundle, build_perception_bundle
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
    "PerceptionBundle",
    "RobotDetection",
    "RobotFrame",
    "RobotIngestEvent",
    "RobotPerceptionBundle",
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
