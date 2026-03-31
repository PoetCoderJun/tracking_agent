from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, is_dataclass
from typing import Any, Deque, DefaultDict, Dict, List, Optional

from backend.perception.models import DerivedObservation, Observation


def _copy_payload(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(key): _copy_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_payload(item) for item in value]
    return value


class PerceptionStore:
    def __init__(
        self,
        *,
        default_window_seconds: float = 5.0,
        sensor_window_seconds: Optional[Dict[str, float]] = None,
        derived_window_seconds: Optional[float] = None,
    ):
        if default_window_seconds <= 0:
            raise ValueError("default_window_seconds must be positive")
        self._default_window_seconds = float(default_window_seconds)
        self._sensor_window_seconds = {
            str(key): float(value) for key, value in dict(sensor_window_seconds or {}).items()
        }
        self._derived_window_seconds = (
            float(derived_window_seconds)
            if derived_window_seconds is not None
            else float(default_window_seconds)
        )
        self._observations: DefaultDict[str, Deque[Observation]] = defaultdict(deque)
        self._derived_by_kind: DefaultDict[str, Deque[DerivedObservation]] = defaultdict(deque)

    def append_observation(self, observation: Observation) -> None:
        queue = self._observations[observation.sensor]
        queue.append(observation)
        self._trim_observations(observation.sensor, now_ms=observation.ts_ms)

    def append_derived(self, derived: DerivedObservation) -> None:
        queue = self._derived_by_kind[derived.kind]
        queue.append(derived)
        self._trim_derived(derived.kind, now_ms=derived.ts_ms)

    def latest(self, sensor: str) -> Optional[Observation]:
        queue = self._observations.get(sensor)
        if not queue:
            return None
        return queue[-1]

    def window(self, sensor: str, *, seconds: Optional[float] = None) -> List[Observation]:
        queue = self._observations.get(sensor)
        if not queue:
            return []
        if seconds is None:
            return list(queue)
        cutoff_ms = queue[-1].ts_ms - round(float(seconds) * 1000)
        return [item for item in queue if item.ts_ms >= cutoff_ms]

    def latest_derived(self, kind: str, *, sensor: Optional[str] = None) -> Optional[DerivedObservation]:
        queue = self._derived_by_kind.get(kind)
        if not queue:
            return None
        if sensor is None:
            return queue[-1]
        for item in reversed(queue):
            if item.sensor == sensor:
                return item
        return None

    def window_derived(
        self,
        kind: str,
        *,
        seconds: Optional[float] = None,
        sensor: Optional[str] = None,
    ) -> List[DerivedObservation]:
        queue = self._derived_by_kind.get(kind)
        if not queue:
            return []
        items = list(queue)
        if sensor is not None:
            items = [item for item in items if item.sensor == sensor]
        if not items or seconds is None:
            return items
        cutoff_ms = items[-1].ts_ms - round(float(seconds) * 1000)
        return [item for item in items if item.ts_ms >= cutoff_ms]

    def latest_as_dict(self, sensor: str) -> Optional[Dict[str, Any]]:
        item = self.latest(sensor)
        return None if item is None else self._observation_as_dict(item)

    def window_as_dicts(self, sensor: str, *, seconds: Optional[float] = None) -> List[Dict[str, Any]]:
        return [self._observation_as_dict(item) for item in self.window(sensor, seconds=seconds)]

    def latest_derived_as_dict(
        self,
        kind: str,
        *,
        sensor: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        item = self.latest_derived(kind, sensor=sensor)
        return None if item is None else self._derived_as_dict(item)

    def window_derived_as_dicts(
        self,
        kind: str,
        *,
        seconds: Optional[float] = None,
        sensor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return [
            self._derived_as_dict(item)
            for item in self.window_derived(kind, seconds=seconds, sensor=sensor)
        ]

    def _observation_as_dict(self, observation: Observation) -> Dict[str, Any]:
        return {
            "id": observation.id,
            "ts_ms": observation.ts_ms,
            "sensor": observation.sensor,
            "kind": observation.kind,
            "payload": _copy_payload(observation.payload),
            "meta": _copy_payload(observation.meta),
        }

    def _derived_as_dict(self, derived: DerivedObservation) -> Dict[str, Any]:
        return {
            "id": derived.id,
            "source_id": derived.source_id,
            "ts_ms": derived.ts_ms,
            "kind": derived.kind,
            "sensor": derived.sensor,
            "payload": _copy_payload(derived.payload),
            "meta": _copy_payload(derived.meta),
        }

    def _trim_observations(self, sensor: str, *, now_ms: int) -> None:
        queue = self._observations[sensor]
        keep_after_ms = now_ms - round(self._sensor_window(sensor) * 1000)
        while queue and queue[0].ts_ms < keep_after_ms:
            queue.popleft()

    def _trim_derived(self, kind: str, *, now_ms: int) -> None:
        queue = self._derived_by_kind[kind]
        keep_after_ms = now_ms - round(self._derived_window_seconds * 1000)
        while queue and queue[0].ts_ms < keep_after_ms:
            queue.popleft()

    def _sensor_window(self, sensor: str) -> float:
        return float(self._sensor_window_seconds.get(sensor, self._default_window_seconds))
