from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from backend.perception.service import LocalPerceptionService


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
