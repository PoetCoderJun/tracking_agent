from __future__ import annotations

import base64
import json
import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_bounding_box_id(payload: Dict[str, Any]) -> Optional[int]:
    raw_value = (
        payload.get("bounding_box_id")
        if isinstance(payload, dict)
        else None
    )
    if raw_value is None and isinstance(payload, dict):
        raw_value = payload.get("bbox_id")
    if raw_value is None and isinstance(payload, dict):
        raw_value = payload.get("target_id")
    if raw_value is None:
        return None
    return int(raw_value)


RESULT_HISTORY_LIMIT = 60


@dataclass(frozen=True)
class BackendDetection:
    track_id: int
    bbox: List[int]
    score: float
    label: str = "person"


@dataclass(frozen=True)
class BackendFrame:
    frame_id: str
    timestamp_ms: int
    image_path: str
    detections: List[BackendDetection]


@dataclass(frozen=True)
class BackendSession:
    session_id: str
    device_id: str
    latest_request_id: Optional[str]
    latest_request_function: Optional[str]
    target_description: str
    latest_memory: str
    latest_target_id: Optional[int]
    latest_target_crop: Optional[str]
    latest_confirmed_frame_path: Optional[str]
    latest_confirmed_detections: List[BackendDetection]
    latest_result: Optional[Dict[str, Any]]
    result_history: List[Dict[str, Any]]
    clarification_notes: List[str]
    conversation_history: List[Dict[str, str]]
    pending_question: Optional[str]
    recent_frames: List[BackendFrame]
    created_at: str
    updated_at: str


class BackendStore:
    def __init__(self, state_root: Path, frame_buffer_size: int = 3):
        if frame_buffer_size <= 0:
            raise ValueError("frame_buffer_size must be positive")
        self._state_root = state_root
        self._frame_buffer_size = frame_buffer_size
        self._lock = threading.RLock()
        self._state_root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        return self._state_root / "sessions" / session_id

    def session_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    def load_session(self, session_id: str) -> BackendSession:
        with self._lock:
            payload = json.loads(self.session_path(session_id).read_text(encoding="utf-8"))
            recent_frames = [
                BackendFrame(
                    frame_id=str(frame["frame_id"]),
                    timestamp_ms=int(frame["timestamp_ms"]),
                    image_path=str(frame["image_path"]),
                    detections=[
                        BackendDetection(
                            track_id=int(detection["track_id"]),
                            bbox=[int(value) for value in detection["bbox"]],
                            score=float(detection.get("score", 1.0)),
                            label=str(detection.get("label", "person")),
                        )
                        for detection in frame.get("detections", [])
                    ],
                )
                for frame in payload.get("recent_frames", [])
            ]
            return BackendSession(
                session_id=str(payload["session_id"]),
                device_id=str(payload.get("device_id", "")),
                latest_request_id=payload.get("latest_request_id"),
                latest_request_function=payload.get("latest_request_function"),
                target_description=str(payload.get("target_description", "")),
                latest_memory=str(payload.get("latest_memory", "")),
                latest_target_id=(
                    None
                    if payload.get("latest_target_id") is None
                    else int(payload["latest_target_id"])
                ),
                latest_target_crop=payload.get("latest_target_crop"),
                latest_confirmed_frame_path=payload.get("latest_confirmed_frame_path"),
                latest_confirmed_detections=[
                    BackendDetection(
                        track_id=int(detection["track_id"]),
                        bbox=[int(value) for value in detection["bbox"]],
                        score=float(detection.get("score", 1.0)),
                        label=str(detection.get("label", "person")),
                    )
                    for detection in payload.get("latest_confirmed_detections", [])
                ],
                latest_result=payload.get("latest_result"),
                result_history=list(payload.get("result_history", [])),
                clarification_notes=[str(note) for note in payload.get("clarification_notes", [])],
                conversation_history=[
                    {
                        "role": str(entry.get("role", "")),
                        "text": str(entry.get("text", "")),
                        "timestamp": str(entry.get("timestamp", "")),
                    }
                    for entry in payload.get("conversation_history", [])
                ],
                pending_question=payload.get("pending_question"),
                recent_frames=recent_frames,
                created_at=str(payload["created_at"]),
                updated_at=str(payload["updated_at"]),
            )

    def load_or_create_session(
        self,
        session_id: str,
        device_id: str,
    ) -> BackendSession:
        with self._lock:
            session_path = self.session_path(session_id)
            if session_path.exists():
                return self.load_session(session_id)

            now = _utc_now()
            session = BackendSession(
                session_id=session_id,
                device_id=device_id,
                latest_request_id=None,
                latest_request_function=None,
                target_description="",
                latest_memory="",
                latest_target_id=None,
                latest_target_crop=None,
                latest_confirmed_frame_path=None,
                latest_confirmed_detections=[],
                latest_result=None,
                result_history=[],
                clarification_notes=[],
                conversation_history=[],
                pending_question=None,
                recent_frames=[],
                created_at=now,
                updated_at=now,
            )
            self._write_session(session)
            return session

    def session_payload(self, session_id: str) -> Dict[str, Any]:
        return asdict(self.load_session(session_id))

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._lock:
            sessions_root = self._state_root / "sessions"
            if not sessions_root.exists():
                return []

            sessions: List[Dict[str, Any]] = []
            for session_dir in sessions_root.iterdir():
                if not session_dir.is_dir():
                    continue
                session_path = session_dir / "session.json"
                if not session_path.exists():
                    continue
                session = self.load_session(session_dir.name)
                sessions.append(
                    {
                        "session_id": session.session_id,
                        "device_id": session.device_id,
                        "updated_at": session.updated_at,
                        "latest_target_id": session.latest_target_id,
                        "latest_result": session.latest_result,
                    }
                )
            sessions.sort(key=lambda item: item["updated_at"], reverse=True)
            return sessions

    def latest_frame(self, session_id: str) -> Optional[BackendFrame]:
        session = self.load_session(session_id)
        if not session.recent_frames:
            return None
        return session.recent_frames[-1]

    def frame_image_path(self, session_id: str, frame_id: str) -> Path:
        session = self.load_session(session_id)
        for frame in session.recent_frames:
            if frame.frame_id == frame_id:
                return Path(frame.image_path)
        raise FileNotFoundError(f"Unknown frame {frame_id} in session {session_id}")

    def ingest_robot_event(
        self,
        session_id: str,
        device_id: str,
        frame: Dict[str, Any],
        detections: List[Dict[str, Any]],
        text: str,
        request_id: Optional[str] = None,
        request_function: Optional[str] = None,
    ) -> BackendSession:
        with self._lock:
            cleaned_text = text.strip()
            session = self.load_or_create_session(
                session_id=session_id,
                device_id=device_id,
            )
            stored_image_path = self._store_frame_image(session_id, frame)
            stored_frame = BackendFrame(
                frame_id=str(frame["frame_id"]),
                timestamp_ms=int(frame["timestamp_ms"]),
                image_path=str(stored_image_path),
                detections=[
                    BackendDetection(
                        track_id=int(detection["track_id"]),
                        bbox=[int(value) for value in detection["bbox"]],
                        score=float(detection.get("score", 1.0)),
                        label=str(detection.get("label", "person")),
                    )
                    for detection in detections
                ],
            )
            updated_frames = [*session.recent_frames, stored_frame][-self._frame_buffer_size :]
            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id or device_id,
                latest_request_id=None if request_id in (None, "") else str(request_id).strip(),
                latest_request_function=(
                    None if request_function in (None, "") else str(request_function).strip()
                ),
                target_description=session.target_description,
                latest_memory=session.latest_memory,
                latest_target_id=session.latest_target_id,
                latest_target_crop=session.latest_target_crop,
                latest_confirmed_frame_path=session.latest_confirmed_frame_path,
                latest_confirmed_detections=session.latest_confirmed_detections,
                latest_result=session.latest_result,
                result_history=session.result_history,
                clarification_notes=session.clarification_notes,
                conversation_history=self._append_conversation_entry(
                    session.conversation_history,
                    role="user",
                    text=cleaned_text,
                ),
                pending_question=session.pending_question,
                recent_frames=updated_frames,
                created_at=session.created_at,
                updated_at=_utc_now(),
            )
            self._write_session(updated)
            return updated

    def append_chat_request(
        self,
        session_id: str,
        device_id: str,
        text: str,
        request_id: str,
    ) -> BackendSession:
        with self._lock:
            cleaned_text = text.strip()
            session = self.load_or_create_session(
                session_id=session_id,
                device_id=device_id,
            )
            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id or device_id,
                latest_request_id=str(request_id).strip(),
                latest_request_function="chat",
                target_description=session.target_description,
                latest_memory=session.latest_memory,
                latest_target_id=session.latest_target_id,
                latest_target_crop=session.latest_target_crop,
                latest_confirmed_frame_path=session.latest_confirmed_frame_path,
                latest_confirmed_detections=session.latest_confirmed_detections,
                latest_result=session.latest_result,
                result_history=session.result_history,
                clarification_notes=session.clarification_notes,
                conversation_history=self._append_conversation_entry(
                    session.conversation_history,
                    role="user",
                    text=cleaned_text,
                ),
                pending_question=session.pending_question,
                recent_frames=session.recent_frames,
                created_at=session.created_at,
                updated_at=_utc_now(),
            )
            self._write_session(updated)
            return updated

    def apply_agent_result(
        self,
        session_id: str,
        result: Dict[str, Any],
    ) -> BackendSession:
        with self._lock:
            session = self.load_session(session_id)
            latest_frame = session.recent_frames[-1] if session.recent_frames else None
            request_id = (
                None
                if result.get("request_id") in (None, "")
                else str(result.get("request_id")).strip()
            )
            if request_id is None:
                request_id = session.latest_request_id
            if session.latest_request_id and request_id and request_id != session.latest_request_id:
                return session
            request_function = (
                None
                if result.get("function") in (None, "")
                else str(result.get("function")).strip()
            )
            if request_function is None:
                request_function = session.latest_request_function
            behavior = str(result.get("behavior", "reply"))
            is_reinitializing = behavior == "init"
            result_frame_id = (
                None
                if result.get("frame_id") in (None, "")
                else str(result.get("frame_id")).strip()
            )
            result_frame = self._frame_by_id(session, result_frame_id) or latest_frame
            target_id = _extract_bounding_box_id(result)
            bbox = self._latest_bbox_for_target(result_frame, target_id)

            raw_memory = str(result.get("memory", "")).strip()
            memory = raw_memory if is_reinitializing else (raw_memory or session.latest_memory)
            target_description = str(result.get("target_description", "")).strip() or session.target_description
            found = bool(result.get("found", False)) and bbox is not None
            visible_bbox = bbox if found else None
            updated_at = _utc_now()
            pending_question = (
                None
                if result.get("pending_question") in (None, "")
                else str(result.get("pending_question")).strip()
            )
            if pending_question is None and result.get("clarification_question") not in (None, ""):
                pending_question = str(result.get("clarification_question")).strip()
            if found and pending_question is None:
                pending_question = None
            latest_result = {
                "request_id": request_id,
                "function": request_function,
                "frame_id": (
                    result_frame_id
                    if result_frame_id is not None
                    else (None if result_frame is None else result_frame.frame_id)
                ),
                "behavior": behavior,
                "text": str(result.get("text", "")).strip(),
                "target_id": None if target_id is None else int(target_id),
                "bbox": visible_bbox,
                "found": found,
                "needs_clarification": bool(result.get("needs_clarification", False)),
                "clarification_question": (
                    None
                    if result.get("clarification_question") in (None, "")
                    else str(result.get("clarification_question")).strip()
                ),
                "memory": memory,
                "robot_response": (
                    dict(result.get("robot_response"))
                    if isinstance(result.get("robot_response"), dict)
                    else None
                ),
            }
            conversation_history = self._append_conversation_entry(
                session.conversation_history,
                role="assistant",
                text=latest_result["text"],
                timestamp=updated_at,
            )
            result_history = [
                *session.result_history,
                {
                    "updated_at": updated_at,
                    **latest_result,
                },
            ][-RESULT_HISTORY_LIMIT:]
            latest_target_crop = (
                result.get("latest_target_crop")
                if is_reinitializing
                else (result.get("latest_target_crop") or session.latest_target_crop)
            )
            latest_confirmed_frame_path = None if is_reinitializing else session.latest_confirmed_frame_path
            latest_confirmed_detections = [] if is_reinitializing else session.latest_confirmed_detections
            if found and result_frame is not None:
                latest_confirmed_frame_path = result_frame.image_path
                latest_confirmed_detections = result_frame.detections
            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id,
                latest_request_id=session.latest_request_id,
                latest_request_function=session.latest_request_function,
                target_description=target_description,
                latest_memory=memory,
                latest_target_id=(
                    None
                    if is_reinitializing and not found
                    else (session.latest_target_id if not found else int(target_id))
                ),
                latest_target_crop=None if latest_target_crop is None else str(latest_target_crop),
                latest_confirmed_frame_path=latest_confirmed_frame_path,
                latest_confirmed_detections=latest_confirmed_detections,
                latest_result=latest_result,
                result_history=result_history,
                clarification_notes=[] if is_reinitializing else session.clarification_notes,
                conversation_history=conversation_history,
                pending_question=pending_question,
                recent_frames=session.recent_frames,
                created_at=session.created_at,
                updated_at=updated_at,
            )
            self._write_session(updated)
            return updated

    def apply_memory_update(
        self,
        session_id: str,
        memory: str,
        expected_frame_id: str,
        expected_target_id: int,
        expected_target_crop: Optional[str],
    ) -> BackendSession:
        with self._lock:
            session = self.load_session(session_id)
            latest_result = session.latest_result
            if latest_result is None:
                return session
            if latest_result.get("frame_id") != expected_frame_id:
                return session
            if session.latest_target_id != int(expected_target_id):
                return session
            if (
                expected_target_crop is not None
                and session.latest_target_crop != str(expected_target_crop)
            ):
                return session

            updated_memory = str(memory).strip() or session.latest_memory
            if not updated_memory or updated_memory == session.latest_memory:
                return session

            updated_latest_result = {
                **latest_result,
                "memory": updated_memory,
            }
            updated_history = list(session.result_history)
            if updated_history:
                last_entry = dict(updated_history[-1])
                if (
                    last_entry.get("frame_id") == expected_frame_id
                    and last_entry.get("target_id") == int(expected_target_id)
                ):
                    last_entry["memory"] = updated_memory
                    updated_history[-1] = last_entry

            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id,
                latest_request_id=session.latest_request_id,
                latest_request_function=session.latest_request_function,
                target_description=session.target_description,
                latest_memory=updated_memory,
                latest_target_id=session.latest_target_id,
                latest_target_crop=session.latest_target_crop,
                latest_confirmed_frame_path=session.latest_confirmed_frame_path,
                latest_confirmed_detections=session.latest_confirmed_detections,
                latest_result=updated_latest_result,
                result_history=updated_history,
                clarification_notes=session.clarification_notes,
                conversation_history=session.conversation_history,
                pending_question=session.pending_question,
                recent_frames=session.recent_frames,
                created_at=session.created_at,
                updated_at=_utc_now(),
            )
            self._write_session(updated)
            return updated

    def add_clarification_note(self, session_id: str, note: str) -> BackendSession:
        with self._lock:
            session = self.load_session(session_id)
            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id,
                latest_request_id=session.latest_request_id,
                latest_request_function=session.latest_request_function,
                target_description=session.target_description,
                latest_memory=session.latest_memory,
                latest_target_id=session.latest_target_id,
                latest_target_crop=session.latest_target_crop,
                latest_confirmed_frame_path=session.latest_confirmed_frame_path,
                latest_confirmed_detections=session.latest_confirmed_detections,
                latest_result=session.latest_result,
                result_history=session.result_history,
                clarification_notes=[*session.clarification_notes, note.strip()],
                conversation_history=session.conversation_history,
                pending_question=session.pending_question,
                recent_frames=session.recent_frames,
                created_at=session.created_at,
                updated_at=_utc_now(),
            )
            self._write_session(updated)
            return updated

    def reset_tracking_context(self, session_id: str) -> BackendSession:
        with self._lock:
            session = self.load_session(session_id)
            latest_frame = session.recent_frames[-1] if session.recent_frames else None
            updated_at = _utc_now()
            latest_result = None
            if latest_frame is not None:
                latest_result = {
                    "frame_id": latest_frame.frame_id,
                    "behavior": "reset",
                    "text": "Tracking context cleared.",
                    "target_id": None,
                    "bbox": None,
                    "found": False,
                    "needs_clarification": False,
                    "clarification_question": None,
                    "memory": "",
                }

            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id,
                latest_request_id=session.latest_request_id,
                latest_request_function=session.latest_request_function,
                target_description="",
                latest_memory="",
                latest_target_id=None,
                latest_target_crop=None,
                latest_confirmed_frame_path=None,
                latest_confirmed_detections=[],
                latest_result=latest_result,
                result_history=[],
                clarification_notes=[],
                conversation_history=session.conversation_history,
                pending_question=None,
                recent_frames=session.recent_frames,
                created_at=session.created_at,
                updated_at=updated_at,
            )
            self._write_session(updated)
            return updated

    def _append_conversation_entry(
        self,
        history: List[Dict[str, str]],
        role: str,
        text: str,
        timestamp: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, str]]:
        cleaned = text.strip()
        if not cleaned:
            return list(history)
        entry = {
            "role": role,
            "text": cleaned,
            "timestamp": timestamp or _utc_now(),
        }
        return [*history, entry][-limit:]

    def _latest_bbox_for_target(
        self,
        latest_frame: Optional[BackendFrame],
        target_id: Any,
    ) -> Optional[List[int]]:
        if latest_frame is None or target_id is None:
            return None
        target_int = int(target_id)
        for detection in latest_frame.detections:
            if detection.track_id == target_int:
                return list(detection.bbox)
        return None

    def _frame_by_id(
        self,
        session: BackendSession,
        frame_id: Optional[str],
    ) -> Optional[BackendFrame]:
        if not frame_id:
            return None
        for frame in session.recent_frames:
            if frame.frame_id == frame_id:
                return frame
        return None

    def _store_frame_image(self, session_id: str, frame: Dict[str, Any]) -> Path:
        frames_dir = self.session_dir(session_id) / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        frame_id = str(frame["frame_id"])

        image_base64 = frame.get("image_base64")
        if image_base64:
            output_path = frames_dir / f"{frame_id}.jpg"
            output_path.write_bytes(base64.b64decode(image_base64))
            return output_path

        image_path = frame.get("image_path")
        if image_path:
            source = Path(str(image_path))
            if source.exists():
                output_path = frames_dir / f"{frame_id}{source.suffix or '.jpg'}"
                shutil.copyfile(source, output_path)
                return output_path
            return source

        image_url = frame.get("image_url")
        if image_url:
            return Path(str(image_url))

        raise ValueError("frame must include one of image_base64, image_path, or image_url")

    def _write_session(self, session: BackendSession) -> None:
        with self._lock:
            session_dir = self.session_dir(session.session_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            session_path = self.session_path(session.session_id)
            tmp_path = session_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(asdict(session), indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
            tmp_path.replace(session_path)
