from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from backend.perception.models import CAMERA_SENSOR_NAME, PERSON_DETECTION_KIND, DerivedObservation, Observation
from backend.perception.recorder import PerceptionRecorder
from backend.perception.store import PerceptionStore
from backend.perception.stream import RobotIngestEvent
from backend.persistence import ActiveSessionStore, LiveSessionStore

_PERCEPTION_STORE_REGISTRY: dict[str, PerceptionStore] = {}


class LocalPerceptionService:
    def __init__(
        self,
        state_root: Path,
        frame_buffer_size: int = 3,
        *,
        observation_window_seconds: float = 5.0,
        recorder_root: Optional[Path] = None,
        save_frame_every_seconds: float = 1.0,
        keyframe_retention_seconds: float = 10.0,
    ):
        self._state_root = state_root
        self._store = LiveSessionStore(state_root=state_root, frame_buffer_size=frame_buffer_size)
        self._observation_window_seconds = float(observation_window_seconds)
        registry_key = str(state_root.resolve())
        self._perception_store = _PERCEPTION_STORE_REGISTRY.setdefault(
            registry_key,
            PerceptionStore(default_window_seconds=observation_window_seconds),
        )
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

    def ensure_session(self, session_id: str, *, device_id: str = "") -> Dict[str, Any]:
        self._store.load_or_create_session(session_id=session_id, device_id=device_id)
        return self.read_snapshot(session_id)

    def start_fresh_session(self, session_id: str, *, device_id: str = "") -> Dict[str, Any]:
        self._store.start_fresh_session(session_id=session_id, device_id=device_id)
        return self.read_snapshot(session_id)

    def prepare_session(
        self,
        *,
        session_id: str,
        device_id: str,
        fresh_session: bool,
        mark_active: bool = True,
    ) -> Dict[str, Any]:
        if fresh_session:
            snapshot = self.start_fresh_session(session_id, device_id=device_id)
        else:
            snapshot = self.ensure_session(session_id, device_id=device_id)
        self.update_stream_status(session_id, status="running")
        if mark_active:
            ActiveSessionStore(self._state_root).write(session_id)
        return snapshot

    def write_observation(
        self,
        event: RobotIngestEvent,
        *,
        request_id: Optional[str] = None,
        request_function: str = "observation",
        frame_payload: Optional[Dict[str, Any]] = None,
        record_conversation: Optional[bool] = None,
    ) -> Dict[str, Any]:
        self._store.load_or_create_session(session_id=event.session_id, device_id=event.device_id)
        self._record_camera_observation(
            event,
            request_id=request_id,
            request_function=request_function,
        )
        return self.read_snapshot(event.session_id)

    def read_snapshot(self, session_id: str) -> Dict[str, Any]:
        persisted = self._read_persisted_snapshot(session_id)
        recent_camera_observations = self._recent_camera_observations_from_memory(session_id=session_id)
        if not recent_camera_observations:
            recent_camera_observations = list((persisted or {}).get("recent_camera_observations") or [])
        latest_camera_observation = self._latest_camera_observation_from_memory(session_id=session_id)
        if latest_camera_observation is None and persisted is not None:
            latest_camera_observation = persisted.get("latest_camera_observation")
        latest_person_detection = self._latest_person_detection_from_memory(session_id=session_id)
        if latest_person_detection is None and persisted is not None:
            latest_person_detection = persisted.get("latest_person_detection")
        return {
            "session_id": session_id,
            "latest_camera_observation": latest_camera_observation,
            "recent_camera_observations": recent_camera_observations,
            "latest_person_detection": latest_person_detection,
            "saved_keyframes": list((persisted or {}).get("saved_keyframes") or []),
            "stream_status": dict((persisted or {}).get("stream_status") or {}),
        }

    def read_latest_frame(self, session_id: str) -> Optional[Dict[str, Any]]:
        latest_observation = self.latest_camera_observation(session_id=session_id)
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

    def latest_camera_observation(self, *, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        latest = self._latest_camera_observation_from_memory(session_id=session_id)
        if latest is not None:
            return latest
        persisted = self._read_persisted_snapshot(self._resolve_session_id(session_id))
        if persisted is None:
            return None
        latest = persisted.get("latest_camera_observation")
        return None if not isinstance(latest, dict) else dict(latest)

    def recent_camera_observations(
        self,
        *,
        seconds: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        observations = self._recent_camera_observations_from_memory(
            seconds=seconds,
            session_id=session_id,
        )
        if observations:
            return observations
        persisted = self._read_persisted_snapshot(self._resolve_session_id(session_id))
        if persisted is None:
            return []
        items = list(persisted.get("recent_camera_observations") or [])
        if not items or seconds is None:
            return items
        cutoff_ms = int(items[-1]["ts_ms"]) - round(float(seconds) * 1000)
        return [item for item in items if int(item.get("ts_ms", 0)) >= cutoff_ms]

    def latest_person_detection(self, *, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        latest = self._latest_person_detection_from_memory(session_id=session_id)
        if latest is not None:
            return latest
        persisted = self._read_persisted_snapshot(self._resolve_session_id(session_id))
        if persisted is not None and isinstance(persisted.get("latest_person_detection"), dict):
            return dict(persisted["latest_person_detection"])
        latest_frame = self.latest_camera_observation(session_id=session_id)
        if latest_frame is None:
            return None
        return {
            "id": f"detection_{latest_frame['id']}",
            "source_id": latest_frame["id"],
            "ts_ms": latest_frame["ts_ms"],
            "kind": PERSON_DETECTION_KIND,
            "sensor": CAMERA_SENSOR_NAME,
            "payload": {"detections": list((latest_frame.get("meta") or {}).get("detections") or [])},
            "meta": {},
        }

    def describe_saved_state(self, *, session_id: Optional[str] = None) -> Dict[str, Any]:
        resolved_session_id = self._resolve_session_id(session_id)
        persisted_payload = (
            self._read_persisted_snapshot(resolved_session_id)
            if resolved_session_id is not None
            else None
        )
        recent_memory = self._recent_camera_observations_from_memory(session_id=resolved_session_id)
        latest_memory = self._latest_camera_observation_from_memory(session_id=resolved_session_id)
        latest_detection = self._latest_person_detection_from_memory(session_id=resolved_session_id)
        return {
            "state_root": str(self._state_root.resolve()),
            "session_id": resolved_session_id,
            "in_memory": {
                "recent_camera_observation_count": len(recent_memory),
                "latest_camera_observation": latest_memory,
                "latest_person_detection": latest_detection,
            },
            "persisted": None
            if persisted_payload is None
            else {
                "snapshot_path": str(self._perception_snapshot_path(resolved_session_id).resolve()),
                "recent_camera_observation_count": len(list(persisted_payload.get("recent_camera_observations") or [])),
                "latest_camera_observation": persisted_payload.get("latest_camera_observation"),
                "latest_person_detection": persisted_payload.get("latest_person_detection"),
                "saved_keyframe_count": len(list(persisted_payload.get("saved_keyframes") or [])),
                "saved_keyframes": list(persisted_payload.get("saved_keyframes") or []),
                "stream_status": dict(persisted_payload.get("stream_status") or {}),
            },
        }

    def update_stream_status(
        self,
        session_id: str,
        *,
        status: str,
        ended_at_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        existing = self._read_persisted_snapshot(session_id) or {
            "session_id": session_id,
            "recent_camera_observations": [],
            "latest_camera_observation": None,
            "latest_person_detection": None,
            "saved_keyframes": [],
            "stream_status": {},
        }
        stream_status = dict(existing.get("stream_status") or {})
        stream_status["status"] = str(status).strip() or "unknown"
        if ended_at_ms is not None:
            stream_status["ended_at_ms"] = int(ended_at_ms)
        elif stream_status.get("status") != "completed":
            stream_status.pop("ended_at_ms", None)
        existing["stream_status"] = stream_status
        self._write_snapshot_payload(session_id=session_id, payload=existing)
        return self.read_snapshot(session_id)

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
        *,
        request_id: Optional[str],
        request_function: str,
    ) -> None:
        detections = [
            {
                "track_id": detection.track_id,
                "bbox": list(detection.bbox),
                "score": detection.score,
                "label": detection.label,
            }
            for detection in event.detections
        ]
        saved_path = None
        if self._recorder is not None:
            saved_path = self._recorder.save_frame_reference(
                sensor=self._camera_sensor_key(event.session_id),
                frame_id=event.frame.frame_id,
                ts_ms=event.frame.timestamp_ms,
                source_path=Path(event.frame.image_path),
            )
        observation = Observation(
            id=event.frame.frame_id,
            ts_ms=event.frame.timestamp_ms,
            sensor=CAMERA_SENSOR_NAME,
            kind="image",
            payload={
                "frame_id": event.frame.frame_id,
                "image_path": str(saved_path or event.frame.image_path),
            },
            meta={
                "session_id": event.session_id,
                "device_id": event.device_id,
                "request_id": request_id,
                "request_function": request_function,
                "text": event.text,
                "detections": detections,
            },
        )
        self._perception_store.append_observation(observation)
        self._perception_store.append_derived(
            DerivedObservation(
                id=f"{event.frame.frame_id}:{PERSON_DETECTION_KIND}",
                source_id=event.frame.frame_id,
                ts_ms=event.frame.timestamp_ms,
                kind=PERSON_DETECTION_KIND,
                sensor=CAMERA_SENSOR_NAME,
                payload={"detections": detections},
                meta={
                    "session_id": event.session_id,
                    "device_id": event.device_id,
                },
            )
        )
        self._write_persisted_snapshot(
            session_id=event.session_id,
            observation=self._observation_as_persisted_dict(observation),
            latest_person_detection={
                "id": f"{event.frame.frame_id}:{PERSON_DETECTION_KIND}",
                "source_id": event.frame.frame_id,
                "ts_ms": event.frame.timestamp_ms,
                "kind": PERSON_DETECTION_KIND,
                "sensor": CAMERA_SENSOR_NAME,
                "payload": {"detections": detections},
                "meta": {
                    "session_id": event.session_id,
                    "device_id": event.device_id,
                },
            },
        )

    def _latest_camera_observation_from_memory(self, *, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        observations = self._recent_camera_observations_from_memory(session_id=session_id)
        if not observations:
            return None
        return observations[-1]

    def _recent_camera_observations_from_memory(
        self,
        *,
        seconds: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        observations = self._perception_store.window_as_dicts(CAMERA_SENSOR_NAME, seconds=seconds)
        if session_id is None:
            return observations
        return [
            item
            for item in observations
            if str((item.get("meta") or {}).get("session_id", "")).strip() == session_id
        ]

    def _latest_person_detection_from_memory(self, *, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        detections = self._perception_store.window_derived_as_dicts(
            PERSON_DETECTION_KIND,
            sensor=CAMERA_SENSOR_NAME,
        )
        if session_id is not None:
            detections = [
                item
                for item in detections
                if str((item.get("meta") or {}).get("session_id", "")).strip() == session_id
            ]
        if not detections:
            return None
        return detections[-1]

    def _write_persisted_snapshot(
        self,
        *,
        session_id: str,
        observation: Dict[str, Any],
        latest_person_detection: Dict[str, Any],
    ) -> None:
        existing = self._read_persisted_snapshot(session_id) or {
            "session_id": session_id,
            "recent_camera_observations": [],
            "latest_camera_observation": None,
            "latest_person_detection": None,
            "saved_keyframes": [],
            "stream_status": {"status": "running"},
        }
        observations = [
            dict(item)
            for item in list(existing.get("recent_camera_observations") or [])
            if isinstance(item, dict)
        ]
        observations.append(dict(observation))
        cutoff_ms = int(observation["ts_ms"]) - round(self._observation_window_seconds * 1000)
        observations = [item for item in observations if int(item.get("ts_ms", 0)) >= cutoff_ms]
        payload = {
            "session_id": session_id,
            "recent_camera_observations": observations,
            "latest_camera_observation": dict(observation),
            "latest_person_detection": dict(latest_person_detection),
            "saved_keyframes": [
                str(path.resolve())
                for path in self._recorder.saved_frame_paths(sensor=self._camera_sensor_key(session_id))
            ],
            "stream_status": dict(existing.get("stream_status") or {"status": "running"}),
        }
        self._write_snapshot_payload(session_id=session_id, payload=payload)

    def _write_snapshot_payload(
        self,
        *,
        session_id: str,
        payload: Dict[str, Any],
    ) -> None:
        snapshot_path = self._perception_snapshot_path(session_id)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def _read_persisted_snapshot(self, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if session_id is None:
            return None
        snapshot_path = self._perception_snapshot_path(session_id)
        if not snapshot_path.exists():
            return None
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _observation_as_persisted_dict(self, observation: Observation) -> Dict[str, Any]:
        return {
            "id": observation.id,
            "ts_ms": observation.ts_ms,
            "sensor": observation.sensor,
            "kind": observation.kind,
            "payload": dict(observation.payload),
            "meta": dict(observation.meta),
        }

    def _camera_sensor_key(self, session_id: str) -> str:
        return str(Path(session_id) / CAMERA_SENSOR_NAME)

    def _perception_snapshot_path(self, session_id: str) -> Path:
        return self._state_root / "perception" / "sessions" / session_id / "snapshot.json"

    def _resolve_session_id(self, session_id: Optional[str]) -> Optional[str]:
        if session_id is not None:
            normalized = str(session_id).strip()
            return normalized or None
        sessions = self._store.list_sessions()
        if not sessions:
            return None
        latest_session_id = str(sessions[0].get("session_id", "")).strip()
        return latest_session_id or None
