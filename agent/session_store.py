from __future__ import annotations

import json
import shutil
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from contextlib import suppress
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
        "reject_reason",
        "decision",
        "needs_clarification",
        "clarification_question",
        "available_targets",
        "summary",
        "sources",
        "search_query",
        "notification_channel",
        "notification_event_type",
        "notification_title",
        "notification_sent_at",
        "notification_outbox_path",
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


def _empty_state() -> Dict[str, Any]:
    return {
        "user_preferences": {},
        "environment": {},
        "runner": {},
        "capabilities": {},
    }


def _normalized_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = _empty_state()
    raw_state = payload.get("state")
    if isinstance(raw_state, dict):
        state["user_preferences"] = _normalized_section(raw_state.get("user_preferences"))
        state["environment"] = _normalized_section(raw_state.get("environment"))
        state["runner"] = _normalized_section(raw_state.get("runner"))
        state["capabilities"] = _normalized_section(raw_state.get("capabilities"))
        return state
    state["user_preferences"] = _normalized_section(payload.get("user_preferences"))
    state["environment"] = _normalized_section(payload.get("environment_map"))
    state["runner"] = _normalized_section(payload.get("runner_state"))
    capabilities = _normalized_section(payload.get("skill_cache"))
    if not capabilities:
        capabilities = _normalized_section(payload.get("capabilities"))
    state["capabilities"] = capabilities
    return state


def _state_with_updates(
    state: Dict[str, Any],
    *,
    user_preferences: Optional[Dict[str, Any]] = None,
    environment_map: Optional[Dict[str, Any]] = None,
    runner_state: Optional[Dict[str, Any]] = None,
    skill_cache: Optional[Dict[str, Any]] = None,
    replace: bool = False,
) -> Dict[str, Any]:
    base = _normalized_state({"state": state})
    updated = _empty_state() if replace else base
    if user_preferences is None:
        updated["user_preferences"] = {} if replace else base["user_preferences"]
    else:
        normalized = _normalized_section(user_preferences)
        updated["user_preferences"] = normalized if replace else _merge_nested(base["user_preferences"], normalized)
    if environment_map is None:
        updated["environment"] = {} if replace else base["environment"]
    else:
        normalized = _normalized_section(environment_map)
        updated["environment"] = normalized if replace else _merge_nested(base["environment"], normalized)
    if runner_state is None:
        updated["runner"] = {} if replace else base["runner"]
    else:
        normalized = _normalized_section(runner_state)
        updated["runner"] = normalized if replace else _merge_nested(base["runner"], normalized)
    if skill_cache is None:
        updated["capabilities"] = {} if replace else base["capabilities"]
    else:
        normalized = _normalized_section(skill_cache)
        updated["capabilities"] = normalized if replace else _merge_nested(base["capabilities"], normalized)
    return updated


def _session_storage_dict(session: "BackendSession") -> Dict[str, Any]:
    payload = asdict(session)
    payload.pop("recent_frames", None)
    payload.pop("state", None)
    payload["state"] = _copy_jsonish(session.state)
    return payload


@dataclass(frozen=True)
class BackendDetection:
    track_id: int
    bbox: List[int]
    score: float
    label: str = "person"


@dataclass(frozen=True)
class BackendSession:
    session_id: str
    device_id: str
    latest_request_id: Optional[str]
    latest_request_function: Optional[str]
    latest_result: Optional[Dict[str, Any]]
    result_history: List[Dict[str, Any]]
    conversation_history: List[Dict[str, str]]
    state: Dict[str, Any]
    created_at: str
    updated_at: str

    @property
    def user_preferences(self) -> Dict[str, Any]:
        return _normalized_section(self.state.get("user_preferences"))

    @property
    def environment_map(self) -> Dict[str, Any]:
        return _normalized_section(self.state.get("environment"))

    @property
    def runner_state(self) -> Dict[str, Any]:
        return _normalized_section(self.state.get("runner"))

    @property
    def skill_cache(self) -> Dict[str, Any]:
        return _normalized_section(self.state.get("capabilities"))


class BackendStore:
    def __init__(self, state_root: Path):
        self._state_root = state_root
        self._state_root.mkdir(parents=True, exist_ok=True)
        registry_key = str(self._state_root.resolve())
        self._lock = _SESSION_STORE_LOCKS.setdefault(registry_key, threading.RLock())

    def session_dir(self, session_id: str) -> Path:
        return self._state_root / "sessions" / session_id

    def session_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    def load_session(self, session_id: str) -> BackendSession:
        with self._lock:
            session_path = self.session_path(session_id)
            last_error: FileNotFoundError | None = None
            payload = None
            for _ in range(5):
                try:
                    raw_text = session_path.read_text(encoding="utf-8")
                    try:
                        payload = json.loads(raw_text)
                    except json.JSONDecodeError:
                        payload, _ = json.JSONDecoder().raw_decode(raw_text)
                    break
                except FileNotFoundError as exc:
                    last_error = exc
                    time.sleep(0.02)
            if payload is None:
                assert last_error is not None
                raise last_error
            return self._session_from_payload(payload)

    def _session_from_payload(self, payload: Dict[str, Any]) -> BackendSession:
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
            state=_normalized_state(payload),
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
                state=_empty_state(),
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
                state=_empty_state(),
                created_at=now,
                updated_at=now,
            )
            self._write_session(session)
            return session

    def session_payload(self, session_id: str) -> Dict[str, Any]:
        return _session_storage_dict(self.load_session(session_id))

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
            # Perception owns observation/frame state; the session keeps only runner/chat state.
            del frame
            del detections
            cleaned_text = text.strip()
            session = self.load_or_create_session(
                session_id=session_id,
                device_id=device_id,
            )
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
                state=_copy_jsonish(session.state),
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
                latest_result=session.latest_result,
                result_history=session.result_history,
                conversation_history=self._append_conversation_entry(
                    session.conversation_history,
                    role="user",
                    text=cleaned_text,
                ),
                state=_copy_jsonish(session.state),
                created_at=session.created_at,
                updated_at=_utc_now(),
            )
            self._write_session(updated)
            return updated

    def apply_agent_result(
        self,
        session_id: str,
        result: Dict[str, Any],
        *,
        session_payload: Optional[Dict[str, Any]] = None,
    ) -> BackendSession:
        with self._lock:
            session = (
                self._session_from_payload(dict(session_payload))
                if isinstance(session_payload, dict)
                else self.load_session(session_id)
            )
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
            latest_result["frame_id"] = result_frame_id
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
                state=_copy_jsonish(session.state),
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
                state=_copy_jsonish(session.state),
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
        runner_state: Optional[Dict[str, Any]] = None,
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
                state=_state_with_updates(
                    session.state,
                    user_preferences=user_preferences,
                    environment_map=environment_map,
                    runner_state=runner_state,
                    skill_cache=skill_cache,
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
        runner_state: Optional[Dict[str, Any]] = None,
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
                state=_state_with_updates(
                    session.state,
                    user_preferences=user_preferences,
                    environment_map=environment_map,
                    runner_state=runner_state,
                    skill_cache=skill_cache,
                    replace=True,
                ),
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
            runner_state={},
            skill_cache={},
        )

    def reset_session_context(self, session_id: str) -> BackendSession:
        with self._lock:
            session = self.load_session(session_id)
            updated_at = _utc_now()
            latest_result = None

            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id,
                latest_request_id=session.latest_request_id,
                latest_request_function=session.latest_request_function,
                latest_result=latest_result,
                result_history=[],
                conversation_history=session.conversation_history,
                state=_copy_jsonish(session.state),
                created_at=session.created_at,
                updated_at=updated_at,
            )
            self._write_session(updated)
            return updated

    def try_acquire_turn(
        self,
        session_id: str,
        *,
        owner_id: str,
        turn_kind: str,
        request_id: str,
        device_id: str = "",
        stale_after_seconds: float = 30.0,
    ) -> BackendSession | None:
        with self._lock:
            session = self.load_or_create_session(session_id=session_id, device_id=device_id)
            runner_state = _normalized_section(session.runner_state)
            now = time.time()

            current_owner_id = str(runner_state.get("owner_id", "") or "").strip()
            current_request_id = str(runner_state.get("turn_request_id", "") or "").strip()
            turn_in_flight = bool(runner_state.get("turn_in_flight", False))
            turn_started_at = runner_state.get("turn_started_at")
            is_stale = False
            if turn_in_flight and turn_started_at not in (None, "") and stale_after_seconds > 0:
                with suppress(TypeError, ValueError):
                    is_stale = (now - float(turn_started_at)) >= stale_after_seconds

            same_turn = (
                turn_in_flight
                and current_owner_id == str(owner_id).strip()
                and current_request_id == str(request_id).strip()
            )
            if turn_in_flight and not is_stale and not same_turn:
                return None

            updated_runner_state = _merge_nested(
                runner_state,
                {
                    "owner_id": str(owner_id).strip(),
                    "turn_in_flight": True,
                    "turn_kind": str(turn_kind).strip(),
                    "turn_request_id": str(request_id).strip(),
                    "turn_started_at": now,
                },
            )
            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id or device_id,
                latest_request_id=session.latest_request_id,
                latest_request_function=session.latest_request_function,
                latest_result=session.latest_result,
                result_history=session.result_history,
                conversation_history=session.conversation_history,
                state=_state_with_updates(session.state, runner_state=updated_runner_state),
                created_at=session.created_at,
                updated_at=_utc_now(),
            )
            self._write_session(updated)
            return updated

    def release_turn(
        self,
        session_id: str,
        *,
        owner_id: str,
        request_id: str | None = None,
        device_id: str = "",
    ) -> BackendSession:
        with self._lock:
            session = self.load_or_create_session(session_id=session_id, device_id=device_id)
            runner_state = _normalized_section(session.runner_state)
            current_owner_id = str(runner_state.get("owner_id", "") or "").strip()
            current_request_id = str(runner_state.get("turn_request_id", "") or "").strip()
            if current_owner_id != str(owner_id).strip():
                return session
            if request_id not in (None, "") and current_request_id != str(request_id).strip():
                return session

            updated_runner_state = _merge_nested(
                runner_state,
                {
                    "owner_id": "",
                    "turn_in_flight": False,
                    "turn_kind": None,
                    "turn_request_id": None,
                    "turn_started_at": None,
                },
            )
            updated = BackendSession(
                session_id=session.session_id,
                device_id=session.device_id or device_id,
                latest_request_id=session.latest_request_id,
                latest_request_function=session.latest_request_function,
                latest_result=session.latest_result,
                result_history=session.result_history,
                conversation_history=session.conversation_history,
                state=_state_with_updates(session.state, runner_state=updated_runner_state),
                created_at=session.created_at,
                updated_at=_utc_now(),
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

    def _write_session(self, session: BackendSession) -> None:
        with self._lock:
            session_dir = self.session_dir(session.session_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            session_path = self.session_path(session.session_id)
            tmp_path = session_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(_session_storage_dict(session), indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
            tmp_path.replace(session_path)


from agent.active_session import (  # noqa: E402
    ActiveSessionRecord,
    ActiveSessionStore,
    resolve_session_id,
)

LiveDetection = BackendDetection
LiveSession = BackendSession
LiveSessionStore = BackendStore

__all__ = [
    "ALLOWED_RESULT_FIELDS",
    "ActiveSessionRecord",
    "ActiveSessionStore",
    "BackendDetection",
    "BackendSession",
    "BackendStore",
    "LiveDetection",
    "LiveSession",
    "LiveSessionStore",
    "resolve_session_id",
]
