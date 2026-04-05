from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from backend.perception.models import CAMERA_SENSOR_NAME, PERSON_DETECTION_KIND
from backend.perception.recorder import PerceptionRecorder
from backend.perception.stream import RobotIngestEvent
from backend.persistence import ActiveSessionStore, LiveSessionStore


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
        return self._read_snapshot_payload(session_id) or self._empty_snapshot_payload(session_id)

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
        persisted = self._read_snapshot_payload(self._resolve_session_id(session_id))
        if persisted is None:
            return None
        latest_observation = persisted.get("latest_camera_observation")
        return None if not isinstance(latest_observation, dict) else dict(latest_observation)

    def recent_camera_observations(
        self,
        *,
        seconds: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        persisted = self._read_snapshot_payload(self._resolve_session_id(session_id))
        if persisted is None:
            return []
        items = list(persisted.get("recent_camera_observations") or [])
        if not items or seconds is None:
            return items
        cutoff_ms = int(items[-1]["ts_ms"]) - round(float(seconds) * 1000)
        return [item for item in items if int(item.get("ts_ms", 0)) >= cutoff_ms]

    def latest_person_detection(self, *, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        persisted = self._read_snapshot_payload(self._resolve_session_id(session_id))
        if persisted is None:
            return None
        latest_detection = persisted.get("latest_person_detection")
        return None if not isinstance(latest_detection, dict) else dict(latest_detection)

    def describe_saved_state(self, *, session_id: Optional[str] = None) -> Dict[str, Any]:
        resolved_session_id = self._resolve_session_id(session_id)
        persisted_payload = self._read_snapshot_payload(resolved_session_id)
        return {
            "state_root": str(self._state_root.resolve()),
            "session_id": resolved_session_id,
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
        existing = self._read_snapshot_payload(session_id) or self._empty_snapshot_payload(session_id)
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
                "session_id": event.session_id,
                "device_id": event.device_id,
                "request_id": request_id,
                "request_function": request_function,
                "text": event.text,
                "detections": detections,
            },
        }
        latest_person_detection = {
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
        }
        self._write_persisted_snapshot(
            session_id=event.session_id,
            observation=observation,
            latest_person_detection=latest_person_detection,
        )

    def _write_persisted_snapshot(
        self,
        *,
        session_id: str,
        observation: Dict[str, Any],
        latest_person_detection: Dict[str, Any],
    ) -> None:
        existing = self._read_snapshot_payload(session_id) or self._empty_snapshot_payload(session_id)
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

    def _read_snapshot_payload(self, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if session_id is None:
            return None
        snapshot_path = self._perception_snapshot_path(session_id)
        if not snapshot_path.exists():
            return None
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid perception snapshot: {snapshot_path}")
        return payload if isinstance(payload, dict) else None

    def _empty_snapshot_payload(self, session_id: str) -> Dict[str, Any]:
        return {
            "session_id": session_id,
            "recent_camera_observations": [],
            "latest_camera_observation": None,
            "latest_person_detection": None,
            "saved_keyframes": [],
            "stream_status": {},
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
