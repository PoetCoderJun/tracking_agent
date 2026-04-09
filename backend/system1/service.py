from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


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


class LocalSystem1Service:
    def __init__(
        self,
        state_root: Path,
        *,
        result_window_seconds: float = 5.0,
    ):
        self._state_root = state_root
        self._result_window_seconds = float(result_window_seconds)

    def prepare(
        self,
        *,
        fresh_state: bool,
        model_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        snapshot = self.reset(model_info=model_info) if fresh_state else self.read_snapshot()
        if model_info:
            self.update_model_info(model_info=model_info)
        self.update_stream_status(status="running")
        return snapshot

    def reset(self, *, model_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        snapshot = self._empty_snapshot_payload()
        if model_info:
            snapshot["model"] = dict(model_info)
        self._write_snapshot_payload(payload=snapshot)
        return self.read_snapshot()

    def read_snapshot(self) -> Dict[str, Any]:
        return self._read_snapshot_payload() or self._empty_snapshot_payload()

    def read_latest_result(self) -> Optional[Dict[str, Any]]:
        latest = self.read_snapshot().get("latest_frame_result")
        return None if not isinstance(latest, dict) else dict(latest)

    def recent_frame_results(self, *, seconds: Optional[float] = None) -> list[Dict[str, Any]]:
        items = list(self.read_snapshot().get("recent_frame_results") or [])
        if not items or seconds is None:
            return items
        cutoff_ms = int(items[-1]["timestamp_ms"]) - round(float(seconds) * 1000)
        return [item for item in items if int(item.get("timestamp_ms", 0)) >= cutoff_ms]

    def write_result(self, frame_result: Dict[str, Any]) -> Dict[str, Any]:
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
        payload = {
            "recent_frame_results": recent_results,
            "latest_frame_result": dict(normalized_result),
            "stream_status": dict(existing.get("stream_status") or {"status": "running"}),
            "model": dict(existing.get("model") or {}),
        }
        self._write_snapshot_payload(payload=payload)
        return self.read_snapshot()

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

    def update_model_info(self, *, model_info: Dict[str, Any]) -> Dict[str, Any]:
        existing = self._read_snapshot_payload() or self._empty_snapshot_payload()
        existing["model"] = dict(model_info or {})
        self._write_snapshot_payload(payload=existing)
        return self.read_snapshot()

    def _write_snapshot_payload(self, *, payload: Dict[str, Any]) -> None:
        snapshot_path = self._snapshot_path()
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def _read_snapshot_payload(self) -> Optional[Dict[str, Any]]:
        snapshot_path = self._snapshot_path()
        if not snapshot_path.exists():
            return None
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid system1 snapshot: {snapshot_path}")
        return {
            "recent_frame_results": [
                _normalized_frame_result(item)
                for item in list(payload.get("recent_frame_results") or [])
                if isinstance(item, dict)
            ],
            "latest_frame_result": None
            if not isinstance(payload.get("latest_frame_result"), dict)
            else _normalized_frame_result(payload.get("latest_frame_result")),
            "stream_status": dict(payload.get("stream_status") or {}),
            "model": dict(payload.get("model") or {}),
        }

    def _empty_snapshot_payload(self) -> Dict[str, Any]:
        return {
            "recent_frame_results": [],
            "latest_frame_result": None,
            "stream_status": {},
            "model": {},
        }

    def _snapshot_path(self) -> Path:
        return self._state_root / "system1" / "snapshot.json"
