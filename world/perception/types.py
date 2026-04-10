from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


CAMERA_SENSOR_NAME = "front_camera"
AUDIO_SENSOR_NAME = "audio"
RADAR_SENSOR_NAME = "radar"
LIDAR_SENSOR_NAME = "lidar"
IMU_SENSOR_NAME = "imu"

PERSON_DETECTION_KIND = "person_detection"


@dataclass(frozen=True)
class Observation:
    id: str
    ts_ms: int
    sensor: str
    kind: str
    payload: Any
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DerivedObservation:
    id: str
    source_id: str
    ts_ms: int
    kind: str
    payload: Dict[str, Any]
    sensor: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


class SensorWorker(Protocol):
    sensor_name: str

    def poll(self) -> List[Observation]:
        ...


class DerivedWorker(Protocol):
    kind: str

    def process(self, observation: Observation) -> List[DerivedObservation]:
        ...
