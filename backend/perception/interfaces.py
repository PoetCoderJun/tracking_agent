from __future__ import annotations

from typing import List, Protocol

from backend.perception.models import DerivedObservation, Observation


class SensorWorker(Protocol):
    sensor_name: str

    def poll(self) -> List[Observation]:
        ...


class DerivedWorker(Protocol):
    kind: str

    def process(self, observation: Observation) -> List[DerivedObservation]:
        ...
