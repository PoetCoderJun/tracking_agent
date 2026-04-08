from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


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
    track_id = int(detection["track_id"])
    if track_id in excluded_track_ids:
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


def normalized_recent_frames(
    raw_session: Dict[str, Any],
    *,
    excluded_track_ids: Any = None,
) -> List[Dict[str, Any]]:
    excluded_track_id_set = _normalized_track_id_set(excluded_track_ids)
    frames: List[Dict[str, Any]] = []
    for frame in list(raw_session.get("recent_frames") or []):
        if not isinstance(frame, dict):
            continue
        frames.append(
            _normalized_frame(
                frame_id=frame.get("frame_id", ""),
                timestamp_ms=frame.get("timestamp_ms", 0),
                image_path=frame.get("image_path", ""),
                detections=frame.get("detections"),
                excluded_track_ids=excluded_track_id_set,
            )
        )
    return frames


def observation_recent_frames(
    *,
    state_root: Path,
    excluded_track_ids: Any = None,
) -> List[Dict[str, Any]]:
    from backend.perception.service import LocalPerceptionService

    excluded_track_id_set = _normalized_track_id_set(excluded_track_ids)
    frames: List[Dict[str, Any]] = []
    service = LocalPerceptionService(state_root)
    for observation in service.recent_camera_observations():
        payload = dict(observation.get("payload") or {})
        frames.append(
            _normalized_frame(
                frame_id=payload.get("frame_id", observation.get("id", "")),
                timestamp_ms=observation.get("ts_ms", 0),
                image_path=payload.get("image_path", ""),
                detections=[],
                excluded_track_ids=excluded_track_id_set,
            )
        )
    return frames


def tracking_recent_frames(
    *,
    state_root: Path,
    session_id: str,
    raw_session: Dict[str, Any],
    excluded_track_ids: Any = None,
) -> List[Dict[str, Any]]:
    session_frames = normalized_recent_frames(raw_session, excluded_track_ids=excluded_track_ids)
    if session_frames:
        return session_frames
    return observation_recent_frames(
        state_root=state_root,
        excluded_track_ids=excluded_track_ids,
    )


def persisted_recent_frames(
    *,
    state_root: Path,
    session_id: str,
) -> List[Dict[str, Any]]:
    session_path = state_root / "sessions" / session_id / "session.json"
    if not session_path.exists():
        return []
    try:
        payload = json.loads(session_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return normalized_recent_frames(payload)


def tracking_frame_count(
    *,
    state_root: Path,
    session_id: str,
) -> int:
    frames = observation_recent_frames(state_root=state_root)
    if frames:
        return len(frames)
    return len(persisted_recent_frames(state_root=state_root, session_id=session_id))


def first_tracking_frame_snapshot(
    *,
    state_root: Path,
    session_id: str,
) -> Dict[str, Any] | None:
    frames = observation_recent_frames(state_root=state_root)
    if not frames:
        frames = persisted_recent_frames(state_root=state_root, session_id=session_id)
    if not frames:
        return None
    return dict(frames[0])
