from __future__ import annotations

import base64
import json
import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_SESSION_STORE_LOCKS: dict[str, threading.RLock] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


RESULT_HISTORY_LIMIT = 8
CONVERSATION_HISTORY_LIMIT = 8
ALLOWED_RESULT_FIELDS = frozenset(
    {
        "request_id",
        "function",
        "behavior",
        "frame_id",
        "target_id",
        "bounding_box_id",
        "found",
        "text",
        "reason",
        "decision",
        "needs_clarification",
        "clarification_question",
        "available_targets",
        "latest_target_crop",
        "summary",
        "robot_response",
    }
)


def _copy_jsonish(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _copy_jsonish(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_jsonish(item) for item in value]
    return value


def _normalized_result_text(result: Dict[str, Any]) -> str:
    return str(result.get("text", "")).strip()


def _normalized_session_result(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: _copy_jsonish(value)
        for key, value in dict(result).items()
        if key in ALLOWED_RESULT_FIELDS
    }


def _normalized_section(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _copy_jsonish(item) for key, item in value.items()}


def _merge_nested(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(dict(merged[key]), value)
            continue
        merged[key] = _copy_jsonish(value)
    return merged


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
    latest_result: Optional[Dict[str, Any]]
    result_history: List[Dict[str, Any]]
    conversation_history: List[Dict[str, str]]
    recent_frames: List[BackendFrame]
    user_preferences: Dict[str, Any]
    environment_map: Dict[str, Any]
    perception_cache: Dict[str, Any]
    skill_cache: Dict[str, Any]
    created_at: str
    updated_at: str


class BackendStore:
    def __init__(self, state_root: Path, frame_buffer_size: int = 3):
        if frame_buffer_size <= 0:
            raise ValueError("frame_buffer_size must be positive")
        self._state_root = state_root
        self._frame_buffer_size = frame_buffer_size
        self._state_root.mkdir(parents=True, exist_ok=True)
        registry_key = str(self._state_root.resolve())
        self._lock = _SESSION_STORE_LOCKS.setdefault(registry_key, threading.RLock())

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
                latest_result=payload.get("latest_result"),
                result_history=list(payload.get("result_history", [])),
                conversation_history=[
                    {
                        "role": str(entry.get("role", "")),
                        "text": str(entry.get("text", "")),
                        "timestamp": str(entry.get("timestamp", "")),
                    }
                    for entry in payload.get("conversation_history", [])
                ],
                recent_frames=recent_frames,
                user_preferences=_normalized_section(payload.get("user_preferences")),
                environment_map=_normalized_section(payload.get("environment_map")),
                perception_cache=_normalized_section(payload.get("perception_cache")),
                skill_cache=_normalized_section(payload.get("skill_cache")),
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
                latest_result=None,
                result_history=[],
                conversation_history=[],
                recent_frames=[],
                user_preferences={},
                environment_map={},
                perception_cache={},
                skill_cache={},
                created_at=now,
                updated_at=now,
            )
            self._write_session(session)
            return session

    def start_fresh_session(
        self,
        session_id: str,
        device_id: str,
    ) -> BackendSession:
        with self._lock:
            session_dir = self.session_dir(session_id)
            if session_dir.exists():
                shutil.rmtree(session_dir)
            now = _utc_now()
            session = BackendSession(
                session_id=session_id,
                device_id=device_id,
                latest_request_id=None,
                latest_request_function=None,
                latest_result=None,
                result_history=[],
                conversation_history=[],
                recent_frames=[],
                user_preferences={},
                environment_map={},
                perception_cache={},
                skill_cache={},
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
        record_conversation: bool = True,
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
                latest_result=session.latest_result,
                result_history=session.result_history,
                conversation_history=(
                    self._append_conversation_entry(
                        session.conversation_history,
                        role="user",
                        text=cleaned_text,
                    )
                    if record_conversation
                    else list(session.conversation_history)
                ),
                recent_frames=updated_frames,
                user_preferences=session.user_preferences,
                environment_map=session.environment_map,
                perception_cache=session.perception_cache,
                skill_cache=session.skill_cache,
                created_at=session.created_at,
                updated_at=_utc_now(),
            )
            self._write_session(updated)
            self._cleanup_session_frames(updated)
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
                latest_result=session.latest_result,
                result_history=session.result_history,
                conversation_history=self._append_conversation_entry(
                    session.conversation_history,
                    role="user",
                    text=cleaned_text,
                ),
                recent_frames=session.recent_frames,
                user_preferences=session.user_preferences,
                environment_map=session.environment_map,
                perception_cache=session.perception_cache,
                skill_cache=session.skill_cache,
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
            result_frame_id = (
                None
                if result.get("frame_id") in (None, "")
                else str(result.get("frame_id")).strip()
            )
            updated_at = _utc_now()
            latest_result = _normalized_session_result(result)
            latest_result["request_id"] = request_id
            latest_result["function"] = request_function
            latest_result["frame_id"] = (
                result_frame_id
                if result_frame_id is not None
                else (None if latest_frame is None else latest_frame.frame_id)
            )
            latest_result["behavior"] = str(result.get("behavior", "result")).strip() or "result"
            latest_result["text"] = _normalized_result_text(result)
            if isinstance(latest_result.get("robot_response"), dict):
                latest_result["robot_response"] = _copy_jsonish(latest_result["robot_response"])
            conversation_history = self._append_conversation_entry(
                session.conversation_history,
                role="assistant",
                text=_normalized_result_text(latest_result),
                timestamp=updated_at,
            )
            result_history = [
                *session.result_history,
                {
                    "updated_at": updated_at,
                    **latest_result,
                },
            ][-RESULT_HISTORY_LIMIT:]
            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id,
                latest_request_id=session.latest_request_id,
                latest_request_function=session.latest_request_function,
                latest_result=latest_result,
                result_history=result_history,
                conversation_history=conversation_history,
                recent_frames=session.recent_frames,
                user_preferences=session.user_preferences,
                environment_map=session.environment_map,
                perception_cache=session.perception_cache,
                skill_cache=session.skill_cache,
                created_at=session.created_at,
                updated_at=updated_at,
            )
            self._write_session(updated)
            return updated

    def patch_latest_result(
        self,
        session_id: str,
        patch: Dict[str, Any],
        *,
        expected_request_id: Optional[str] = None,
        expected_frame_id: Optional[str] = None,
    ) -> BackendSession:
        with self._lock:
            session = self.load_session(session_id)
            latest_result = session.latest_result
            if latest_result is None:
                return session
            if (
                expected_request_id not in (None, "")
                and latest_result.get("request_id") != str(expected_request_id).strip()
            ):
                return session
            if (
                expected_frame_id not in (None, "")
                and latest_result.get("frame_id") != str(expected_frame_id).strip()
            ):
                return session
            if not patch:
                return session

            updated_latest_result = dict(latest_result)
            changed = False
            normalized_patch = _normalized_session_result(dict(patch))
            for key, value in normalized_patch.items():
                copied_value = _copy_jsonish(value)
                if updated_latest_result.get(key) == copied_value:
                    continue
                updated_latest_result[key] = copied_value
                changed = True
            if not changed:
                return session

            updated_history = list(session.result_history)
            if updated_history:
                last_entry = dict(updated_history[-1])
                if last_entry.get("request_id") == updated_latest_result.get("request_id"):
                    for key, value in normalized_patch.items():
                        last_entry[key] = _copy_jsonish(value)
                    updated_history[-1] = last_entry

            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id,
                latest_request_id=session.latest_request_id,
                latest_request_function=session.latest_request_function,
                latest_result=updated_latest_result,
                result_history=updated_history,
                conversation_history=session.conversation_history,
                recent_frames=session.recent_frames,
                user_preferences=session.user_preferences,
                environment_map=session.environment_map,
                perception_cache=session.perception_cache,
                skill_cache=session.skill_cache,
                created_at=session.created_at,
                updated_at=_utc_now(),
            )
            self._write_session(updated)
            return updated

    def patch_agent_state(
        self,
        session_id: str,
        *,
        device_id: str = "",
        user_preferences: Optional[Dict[str, Any]] = None,
        environment_map: Optional[Dict[str, Any]] = None,
        perception_cache: Optional[Dict[str, Any]] = None,
        skill_cache: Optional[Dict[str, Any]] = None,
    ) -> BackendSession:
        with self._lock:
            session = self.load_or_create_session(session_id=session_id, device_id=device_id)
            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id or device_id,
                latest_request_id=session.latest_request_id,
                latest_request_function=session.latest_request_function,
                latest_result=session.latest_result,
                result_history=session.result_history,
                conversation_history=session.conversation_history,
                recent_frames=session.recent_frames,
                user_preferences=(
                    session.user_preferences
                    if user_preferences is None
                    else _merge_nested(session.user_preferences, _normalized_section(user_preferences))
                ),
                environment_map=(
                    session.environment_map
                    if environment_map is None
                    else _merge_nested(session.environment_map, _normalized_section(environment_map))
                ),
                perception_cache=(
                    session.perception_cache
                    if perception_cache is None
                    else _merge_nested(session.perception_cache, _normalized_section(perception_cache))
                ),
                skill_cache=(
                    session.skill_cache
                    if skill_cache is None
                    else _merge_nested(session.skill_cache, _normalized_section(skill_cache))
                ),
                created_at=session.created_at,
                updated_at=_utc_now(),
            )
            self._write_session(updated)
            return updated

    def replace_agent_state(
        self,
        session_id: str,
        *,
        device_id: str = "",
        user_preferences: Optional[Dict[str, Any]] = None,
        environment_map: Optional[Dict[str, Any]] = None,
        perception_cache: Optional[Dict[str, Any]] = None,
        skill_cache: Optional[Dict[str, Any]] = None,
    ) -> BackendSession:
        with self._lock:
            session = self.load_or_create_session(session_id=session_id, device_id=device_id)
            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id or device_id,
                latest_request_id=session.latest_request_id,
                latest_request_function=session.latest_request_function,
                latest_result=session.latest_result,
                result_history=session.result_history,
                conversation_history=session.conversation_history,
                recent_frames=session.recent_frames,
                user_preferences=_normalized_section(
                    session.user_preferences if user_preferences is None else user_preferences
                ),
                environment_map=_normalized_section(
                    session.environment_map if environment_map is None else environment_map
                ),
                perception_cache=_normalized_section(
                    session.perception_cache if perception_cache is None else perception_cache
                ),
                skill_cache=_normalized_section(session.skill_cache if skill_cache is None else skill_cache),
                created_at=session.created_at,
                updated_at=_utc_now(),
            )
            self._write_session(updated)
            return updated

    def reset_agent_state(self, session_id: str, *, device_id: str = "") -> BackendSession:
        return self.replace_agent_state(
            session_id,
            device_id=device_id,
            user_preferences={},
            environment_map={},
            perception_cache={},
            skill_cache={},
        )

    def reset_session_context(self, session_id: str) -> BackendSession:
        with self._lock:
            session = self.load_session(session_id)
            latest_frame = session.recent_frames[-1] if session.recent_frames else None
            updated_at = _utc_now()
            latest_result = None
            if latest_frame is not None:
                latest_result = {
                    "request_id": session.latest_request_id,
                    "function": session.latest_request_function,
                    "frame_id": latest_frame.frame_id,
                    "behavior": "reset_context",
                    "text": "Session context cleared.",
                }

            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id,
                latest_request_id=session.latest_request_id,
                latest_request_function=session.latest_request_function,
                latest_result=latest_result,
                result_history=[],
                conversation_history=session.conversation_history,
                recent_frames=session.recent_frames,
                user_preferences=session.user_preferences,
                environment_map=session.environment_map,
                perception_cache=session.perception_cache,
                skill_cache=session.skill_cache,
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
        limit: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        cleaned = text.strip()
        if not cleaned:
            return list(history)
        entry = {
            "role": role,
            "text": cleaned,
            "timestamp": timestamp or _utc_now(),
        }
        updated_history = [*history, entry]
        if limit is None:
            limit = CONVERSATION_HISTORY_LIMIT
        return updated_history[-limit:]

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
                if source.resolve() == output_path.resolve():
                    return output_path
                shutil.copyfile(source, output_path)
                return output_path
            return source

        image_url = frame.get("image_url")
        if image_url:
            return Path(str(image_url))

        raise ValueError("frame must include one of image_base64, image_path, or image_url")

    def _cleanup_session_frames(self, session: BackendSession) -> None:
        frames_dir = self.session_dir(session.session_id) / "frames"
        if not frames_dir.exists():
            return

        pinned_paths: set[Path] = set()
        for frame in session.recent_frames:
            try:
                frame_path = Path(str(frame.image_path)).resolve()
            except OSError:
                continue
            if frame_path.parent == frames_dir.resolve():
                pinned_paths.add(frame_path)

        for candidate in frames_dir.iterdir():
            if not candidate.is_file():
                continue
            if candidate.resolve() in pinned_paths:
                continue
            candidate.unlink(missing_ok=True)

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
