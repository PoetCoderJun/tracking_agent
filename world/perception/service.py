from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from world.perception.types import CAMERA_SENSOR_NAME
from world.perception.recorder import PerceptionRecorder
from world.perception.stream import RobotIngestEvent


def _normalized_detection(raw: Any) -> Dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    bbox = raw.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    track_id = raw.get("track_id")
    if track_id not in (None, ""):
        track_id = int(track_id)
    return {
        "track_id": track_id,
        "bbox": [int(value) for value in bbox],
        "score": float(raw.get("score", 1.0)),
        "label": str(raw.get("label", "person")).strip() or "person",
    }


def _normalized_frame_result(raw: Any) -> Dict[str, Any]:
    raw_result = dict(raw or {})
    detections = []
    for detection in list(raw_result.get("detections") or []):
        normalized_detection = _normalized_detection(detection)
        if normalized_detection is not None:
            detections.append(normalized_detection)
    return {
        "frame_id": str(raw_result.get("frame_id", "")).strip(),
        "timestamp_ms": int(raw_result.get("timestamp_ms", 0)),
        "image_path": str(raw_result.get("image_path", "")).strip(),
        "detections": detections,
    }


class LocalPerceptionService:
    def __init__(
        self,
        state_root: Path,
        *,
        observation_window_seconds: float = 5.0,
        result_window_seconds: float = 5.0,
        recorder_root: Optional[Path] = None,
        save_frame_every_seconds: float = 1.0,
        keyframe_retention_seconds: float = 10.0,
    ):
        self._state_root = state_root
        self._observation_window_seconds = float(observation_window_seconds)
        self._result_window_seconds = float(result_window_seconds)
        self._recorder = (
            None
            if recorder_root is None
            else PerceptionRecorder(
                recorder_root,
                save_frame_every_seconds=save_frame_every_seconds,
                retention_seconds=keyframe_retention_seconds,
            )
        )
        if self._recorder is None:
            self._recorder = PerceptionRecorder(
                self._state_root / "perception" / "keyframes",
                save_frame_every_seconds=save_frame_every_seconds,
                retention_seconds=keyframe_retention_seconds,
            )

    def prepare(self, *, fresh_state: bool) -> Dict[str, Any]:
        snapshot = self.reset() if fresh_state else self.read_snapshot()
        self.update_stream_status(status="running")
        return snapshot

    def prepare_system1(
        self,
        *,
        fresh_state: bool,
        model_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        snapshot = self.reset_system1(model_info=model_info) if fresh_state else self.read_snapshot()
        if model_info:
            self.update_model_info(model_info=model_info)
        self.update_stream_status(status="running")
        return snapshot

    def reset(self) -> Dict[str, Any]:
        if self._recorder is not None:
            self._recorder.clear()
        snapshot = self._empty_snapshot_payload()
        self._write_snapshot_payload(payload=snapshot)
        return self.read_snapshot()

    def reset_system1(self, *, model_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        existing = self._read_snapshot_payload() or self._empty_snapshot_payload()
        existing["recent_frame_results"] = []
        existing["latest_frame_result"] = None
        existing["model"] = {} if model_info is None else dict(model_info)
        latest_observation = existing.get("latest_camera_observation")
        if isinstance(latest_observation, dict):
            meta = dict(latest_observation.get("meta") or {})
            meta["detections"] = []
            existing["latest_camera_observation"] = {**latest_observation, "meta": meta}
        latest_frame = existing.get("latest_frame")
        if isinstance(latest_frame, dict):
            updated_latest_frame = dict(latest_frame)
            updated_latest_frame["detections"] = []
            existing["latest_frame"] = updated_latest_frame
        recent_observations = []
        for observation in list(existing.get("recent_camera_observations") or []):
            if not isinstance(observation, dict):
                continue
            meta = dict(observation.get("meta") or {})
            meta["detections"] = []
            recent_observations.append({**observation, "meta": meta})
        existing["recent_camera_observations"] = recent_observations
        self._write_snapshot_payload(payload=existing)
        return self.read_snapshot()

    def write_observation(
        self,
        event: RobotIngestEvent,
    ) -> Dict[str, Any]:
        self._record_camera_observation(event)
        return self.read_snapshot()

    def read_snapshot(self) -> Dict[str, Any]:
        return self._read_snapshot_payload() or self._empty_snapshot_payload()

    def read_latest_frame(self) -> Optional[Dict[str, Any]]:
        persisted = self._read_snapshot_payload()
        if persisted is not None:
            latest_frame = persisted.get("latest_frame")
            if isinstance(latest_frame, dict):
                return dict(latest_frame)
        latest_observation = self.latest_camera_observation()
        if latest_observation is None:
            return None
        payload = dict(latest_observation.get("payload") or {})
        meta = dict(latest_observation.get("meta") or {})
        return {
            "frame_id": str(payload.get("frame_id", latest_observation.get("id", ""))).strip(),
            "timestamp_ms": int(latest_observation.get("ts_ms", 0)),
            "image_path": str(payload.get("image_path", "")).strip(),
            "detections": list(meta.get("detections") or []),
        }

    def read_latest_frame_result(self) -> Optional[Dict[str, Any]]:
        latest = self.read_snapshot().get("latest_frame_result")
        return None if not isinstance(latest, dict) else dict(latest)

    def latest_camera_observation(self) -> Optional[Dict[str, Any]]:
        persisted = self._read_snapshot_payload()
        if persisted is None:
            return None
        latest_observation = persisted.get("latest_camera_observation")
        return None if not isinstance(latest_observation, dict) else dict(latest_observation)

    def recent_camera_observations(
        self,
        *,
        seconds: Optional[float] = None,
    ) -> list[Dict[str, Any]]:
        persisted = self._read_snapshot_payload()
        if persisted is None:
            return []
        items = list(persisted.get("recent_camera_observations") or [])
        if not items or seconds is None:
            return items
        cutoff_ms = int(items[-1]["ts_ms"]) - round(float(seconds) * 1000)
        return [item for item in items if int(item.get("ts_ms", 0)) >= cutoff_ms]

    def recent_frame_results(self, *, seconds: Optional[float] = None) -> list[Dict[str, Any]]:
        items = list(self.read_snapshot().get("recent_frame_results") or [])
        if not items or seconds is None:
            return items
        cutoff_ms = int(items[-1]["timestamp_ms"]) - round(float(seconds) * 1000)
        return [item for item in items if int(item.get("timestamp_ms", 0)) >= cutoff_ms]

    def describe_saved_state(self) -> Dict[str, Any]:
        persisted_payload = self._read_snapshot_payload()
        return {
            "state_root": str(self._state_root.resolve()),
            "persisted": None
            if persisted_payload is None
            else {
                "snapshot_path": str(self._perception_snapshot_path().resolve()),
                "recent_camera_observation_count": len(list(persisted_payload.get("recent_camera_observations") or [])),
                "latest_frame": persisted_payload.get("latest_frame"),
                "latest_camera_observation": persisted_payload.get("latest_camera_observation"),
                "latest_frame_result": persisted_payload.get("latest_frame_result"),
                "recent_frame_results": list(persisted_payload.get("recent_frame_results") or []),
                "model": dict(persisted_payload.get("model") or {}),
                "saved_keyframe_count": len(list(persisted_payload.get("saved_keyframes") or [])),
                "saved_keyframes": list(persisted_payload.get("saved_keyframes") or []),
                "stream_status": dict(persisted_payload.get("stream_status") or {}),
            },
        }

    def update_stream_status(
        self,
        *,
        status: str,
        ended_at_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        existing = self._read_snapshot_payload() or self._empty_snapshot_payload()
        stream_status = dict(existing.get("stream_status") or {})
        stream_status["status"] = str(status).strip() or "unknown"
        if ended_at_ms is not None:
            stream_status["ended_at_ms"] = int(ended_at_ms)
        elif stream_status.get("status") != "completed":
            stream_status.pop("ended_at_ms", None)
        existing["stream_status"] = stream_status
        self._write_snapshot_payload(payload=existing)
        return self.read_snapshot()

    def write_frame_result(self, frame_result: Dict[str, Any]) -> Dict[str, Any]:
        normalized_result = _normalized_frame_result(frame_result)
        existing = self._read_snapshot_payload() or self._empty_snapshot_payload()
        recent_results = [
            _normalized_frame_result(item)
            for item in list(existing.get("recent_frame_results") or [])
            if isinstance(item, dict)
        ]
        recent_results = [item for item in recent_results if item["frame_id"] != normalized_result["frame_id"]]
        recent_results.append(normalized_result)
        cutoff_ms = int(normalized_result["timestamp_ms"]) - round(self._result_window_seconds * 1000)
        recent_results = [item for item in recent_results if int(item.get("timestamp_ms", 0)) >= cutoff_ms]

        latest_observation = existing.get("latest_camera_observation")
        recent_observations = [
            dict(item)
            for item in list(existing.get("recent_camera_observations") or [])
            if isinstance(item, dict)
        ]
        for observation in recent_observations:
            payload = dict(observation.get("payload") or {})
            if str(payload.get("frame_id", observation.get("id", ""))).strip() != normalized_result["frame_id"]:
                continue
            meta = dict(observation.get("meta") or {})
            meta["detections"] = list(normalized_result["detections"])
            observation["meta"] = meta
        if isinstance(latest_observation, dict):
            payload = dict(latest_observation.get("payload") or {})
            if str(payload.get("frame_id", latest_observation.get("id", ""))).strip() == normalized_result["frame_id"]:
                meta = dict(latest_observation.get("meta") or {})
                meta["detections"] = list(normalized_result["detections"])
                latest_observation = {**latest_observation, "meta": meta}

        latest_frame = dict(existing.get("latest_frame") or {})
        if str(latest_frame.get("frame_id", "")).strip() == normalized_result["frame_id"]:
            latest_frame["detections"] = list(normalized_result["detections"])

        payload = {
            **existing,
            "recent_camera_observations": recent_observations,
            "latest_camera_observation": latest_observation,
            "latest_frame": latest_frame or existing.get("latest_frame"),
            "recent_frame_results": recent_results,
            "latest_frame_result": dict(normalized_result),
        }
        self._write_snapshot_payload(payload=payload)
        return self.read_snapshot()

    def update_model_info(self, *, model_info: Dict[str, Any]) -> Dict[str, Any]:
        existing = self._read_snapshot_payload() or self._empty_snapshot_payload()
        existing["model"] = dict(model_info or {})
        self._write_snapshot_payload(payload=existing)
        return self.read_snapshot()

    def save_frame_reference(
        self,
        *,
        frame_id: str,
        ts_ms: int,
        source_path: Path,
        force: bool = False,
    ) -> Optional[Path]:
        if self._recorder is None:
            return None
        return self._recorder.save_frame_reference(
            sensor=CAMERA_SENSOR_NAME,
            frame_id=frame_id,
            ts_ms=ts_ms,
            source_path=source_path,
            force=force,
        )

    def _record_camera_observation(
        self,
        event: RobotIngestEvent,
    ) -> None:
        saved_path = None
        if self._recorder is not None:
            saved_path = self._recorder.save_frame_reference(
                sensor=CAMERA_SENSOR_NAME,
                frame_id=event.frame.frame_id,
                ts_ms=event.frame.timestamp_ms,
                source_path=Path(event.frame.image_path),
            )
        observation = {
            "id": event.frame.frame_id,
            "ts_ms": event.frame.timestamp_ms,
            "sensor": CAMERA_SENSOR_NAME,
            "kind": "image",
            "payload": {
                "frame_id": event.frame.frame_id,
                "image_path": str(saved_path or event.frame.image_path),
            },
            "meta": {
                "detections": [
                    {
                        "track_id": None if int(detection.track_id) < 0 else int(detection.track_id),
                        "bbox": [int(value) for value in detection.bbox],
                        "score": float(detection.score),
                        "label": str(detection.label).strip() or "person",
                    }
                    for detection in list(event.detections or [])
                ],
            },
        }
        self._write_persisted_snapshot(observation=observation)

    def _write_persisted_snapshot(
        self,
        *,
        observation: Dict[str, Any],
    ) -> None:
        existing = self._read_snapshot_payload() or self._empty_snapshot_payload()
        observations = [
            dict(item)
            for item in list(existing.get("recent_camera_observations") or [])
            if isinstance(item, dict)
        ]
        observations.append(dict(observation))
        cutoff_ms = int(observation["ts_ms"]) - round(self._observation_window_seconds * 1000)
        observations = [item for item in observations if int(item.get("ts_ms", 0)) >= cutoff_ms]
        payload = {
            "recent_camera_observations": observations,
            "latest_frame": {
                "frame_id": str((observation.get("payload") or {}).get("frame_id", observation.get("id", ""))).strip(),
                "timestamp_ms": int(observation.get("ts_ms", 0)),
                "image_path": str((observation.get("payload") or {}).get("image_path", "")).strip(),
                "detections": list((observation.get("meta") or {}).get("detections") or []),
            },
            "latest_camera_observation": dict(observation),
            "recent_frame_results": list(existing.get("recent_frame_results") or []),
            "latest_frame_result": existing.get("latest_frame_result"),
            "model": dict(existing.get("model") or {}),
            "saved_keyframes": [
                str(path.resolve())
                for path in self._recorder.saved_frame_paths(sensor=CAMERA_SENSOR_NAME)
            ],
            "stream_status": dict(existing.get("stream_status") or {"status": "running"}),
        }
        self._write_snapshot_payload(payload=payload)

    def _write_snapshot_payload(
        self,
        *,
        payload: Dict[str, Any],
    ) -> None:
        snapshot_path = self._perception_snapshot_path()
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def _read_snapshot_payload(self) -> Optional[Dict[str, Any]]:
        snapshot_path = self._perception_snapshot_path()
        if not snapshot_path.exists():
            return None
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid perception snapshot: {snapshot_path}")
        return {
            "recent_camera_observations": [
                dict(item)
                for item in list(payload.get("recent_camera_observations") or [])
                if isinstance(item, dict)
            ],
            "latest_frame": None
            if not isinstance(payload.get("latest_frame"), dict)
            else dict(payload.get("latest_frame") or {}),
            "latest_camera_observation": None
            if not isinstance(payload.get("latest_camera_observation"), dict)
            else dict(payload.get("latest_camera_observation") or {}),
            "recent_frame_results": [
                _normalized_frame_result(item)
                for item in list(payload.get("recent_frame_results") or [])
                if isinstance(item, dict)
            ],
            "latest_frame_result": None
            if not isinstance(payload.get("latest_frame_result"), dict)
            else _normalized_frame_result(payload.get("latest_frame_result")),
            "model": dict(payload.get("model") or {}),
            "saved_keyframes": [str(path) for path in list(payload.get("saved_keyframes") or [])],
            "stream_status": dict(payload.get("stream_status") or {}),
        }

    def _empty_snapshot_payload(self) -> Dict[str, Any]:
        return {
            "recent_camera_observations": [],
            "latest_frame": None,
            "latest_camera_observation": None,
            "recent_frame_results": [],
            "latest_frame_result": None,
            "model": {},
            "saved_keyframes": [],
            "stream_status": {},
        }

    def _perception_snapshot_path(self) -> Path:
        return self._state_root / "perception" / "snapshot.json"
