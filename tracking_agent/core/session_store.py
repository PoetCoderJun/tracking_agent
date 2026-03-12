from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from tracking_agent.memory_format import normalize_memory_markdown


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TrackingSession:
    session_id: str
    target_description: str
    status: str
    created_at: str
    updated_at: str
    memory_path: str
    latest_result_path: Optional[str]
    latest_target_crop_path: Optional[str]
    latest_visualization_path: Optional[str]
    latest_confirmed_frame_path: Optional[str]
    reference_crop_paths: List[str]
    clarification_notes: List[str]
    pending_clarification_question: Optional[str]


class SessionStore:
    def __init__(self, sessions_root: Path):
        self._sessions_root = sessions_root
        self._sessions_root.mkdir(parents=True, exist_ok=True)

    def create_or_reset_session(
        self,
        session_id: str,
        target_description: str,
        initial_memory: str,
    ) -> TrackingSession:
        session_dir = self.session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        memory_path = session_dir / "memory.md"
        state_path = session_dir / "session.json"

        normalized_memory = normalize_memory_markdown(initial_memory)
        memory_path.write_text(normalized_memory, encoding="utf-8")

        timestamp = _utc_now()
        session = TrackingSession(
            session_id=session_id,
            target_description=target_description,
            status="initialized",
            created_at=timestamp,
            updated_at=timestamp,
            memory_path=str(memory_path),
            latest_result_path=None,
            latest_target_crop_path=None,
            latest_visualization_path=None,
            latest_confirmed_frame_path=None,
            reference_crop_paths=[],
            clarification_notes=[],
            pending_clarification_question=None,
        )
        self._write_session_state(session, state_path)
        return self.load_session(session_id)

    def session_dir(self, session_id: str) -> Path:
        return self._sessions_root / session_id

    def load_session(self, session_id: str) -> TrackingSession:
        state_path = self.session_dir(session_id) / "session.json"
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload.setdefault("latest_target_crop_path", None)
        payload.setdefault("latest_visualization_path", None)
        payload.setdefault("latest_confirmed_frame_path", None)
        payload.setdefault("reference_crop_paths", [])
        payload.setdefault("clarification_notes", [])
        payload.setdefault("pending_clarification_question", None)
        return TrackingSession(**payload)

    def read_memory(self, session_id: str) -> str:
        session = self.load_session(session_id)
        return Path(session.memory_path).read_text(encoding="utf-8")

    def write_memory(self, session_id: str, memory_markdown: str) -> TrackingSession:
        session = self.load_session(session_id)
        normalized = normalize_memory_markdown(memory_markdown)
        Path(session.memory_path).write_text(normalized, encoding="utf-8")
        updated = TrackingSession(
            **{
                **asdict(session),
                "updated_at": _utc_now(),
            }
        )
        self._write_session_state(updated, self.session_dir(session_id) / "session.json")
        return updated

    def write_latest_result(self, session_id: str, result: Dict[str, Any]) -> TrackingSession:
        session = self.load_session(session_id)
        result_path = self.session_dir(session_id) / "latest_result.json"
        result_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        updated = TrackingSession(
            **{
                **asdict(session),
                "latest_result_path": str(result_path),
                "updated_at": _utc_now(),
            }
        )
        self._write_session_state(updated, self.session_dir(session_id) / "session.json")
        return updated

    def set_latest_target_crop_path(
        self,
        session_id: str,
        crop_path: Path,
    ) -> TrackingSession:
        session = self.load_session(session_id)
        updated = TrackingSession(
            **{
                **asdict(session),
                "latest_target_crop_path": str(crop_path),
                "updated_at": _utc_now(),
            }
        )
        self._write_session_state(updated, self.session_dir(session_id) / "session.json")
        return updated

    def set_latest_visualization_path(
        self,
        session_id: str,
        visualization_path: Path,
    ) -> TrackingSession:
        session = self.load_session(session_id)
        updated = TrackingSession(
            **{
                **asdict(session),
                "latest_visualization_path": str(visualization_path),
                "updated_at": _utc_now(),
            }
        )
        self._write_session_state(updated, self.session_dir(session_id) / "session.json")
        return updated

    def set_latest_confirmed_frame_path(
        self,
        session_id: str,
        frame_path: Path,
    ) -> TrackingSession:
        session = self.load_session(session_id)
        updated = TrackingSession(
            **{
                **asdict(session),
                "latest_confirmed_frame_path": str(frame_path),
                "updated_at": _utc_now(),
            }
        )
        self._write_session_state(updated, self.session_dir(session_id) / "session.json")
        return updated

    def add_reference_crop(
        self,
        session_id: str,
        crop_path: Path,
        max_crops: int = 3,
    ) -> TrackingSession:
        session = self.load_session(session_id)
        crop_str = str(crop_path)
        existing = [path for path in session.reference_crop_paths if path != crop_str]
        preserved = existing if len(existing) <= 2 else [existing[0], existing[-1]]
        updated_paths = [*preserved, crop_str][-max_crops:]

        updated = TrackingSession(
            **{
                **asdict(session),
                "latest_target_crop_path": crop_str,
                "reference_crop_paths": updated_paths,
                "updated_at": _utc_now(),
            }
        )
        self._write_session_state(updated, self.session_dir(session_id) / "session.json")
        return updated

    def update_status(
        self,
        session_id: str,
        status: str,
        pending_clarification_question: Optional[str] = None,
    ) -> TrackingSession:
        session = self.load_session(session_id)
        updated = TrackingSession(
            **{
                **asdict(session),
                "status": status,
                "pending_clarification_question": pending_clarification_question,
                "updated_at": _utc_now(),
            }
        )
        self._write_session_state(updated, self.session_dir(session_id) / "session.json")
        return updated

    def add_clarification_note(self, session_id: str, note: str) -> TrackingSession:
        session = self.load_session(session_id)
        notes = list(session.clarification_notes)
        notes.append(note.strip())
        updated = TrackingSession(
            **{
                **asdict(session),
                "clarification_notes": notes,
                "updated_at": _utc_now(),
            }
        )
        self._write_session_state(updated, self.session_dir(session_id) / "session.json")
        return updated

    def _write_session_state(self, session: TrackingSession, state_path: Path) -> None:
        state_path.write_text(
            json.dumps(asdict(session), indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
