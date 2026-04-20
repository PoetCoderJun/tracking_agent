from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ActiveSessionRecord:
    session_id: str
    updated_at: str


class ActiveSessionStore:
    def __init__(self, state_root: Path):
        self._state_root = state_root
        self._state_root.mkdir(parents=True, exist_ok=True)

    def path(self) -> Path:
        return self._state_root / "active_session.json"

    def load(self) -> ActiveSessionRecord:
        payload = json.loads(self.path().read_text(encoding="utf-8"))
        return ActiveSessionRecord(
            session_id=str(payload["session_id"]),
            updated_at=str(payload["updated_at"]),
        )

    def load_if_exists(self) -> Optional[ActiveSessionRecord]:
        path = self.path()
        if not path.exists():
            return None
        return self.load()

    def current_session_id(self) -> Optional[str]:
        record = self.load_if_exists()
        if record is None:
            return None
        session_id = record.session_id.strip()
        return session_id or None

    def write(self, session_id: str) -> ActiveSessionRecord:
        cleaned_session_id = str(session_id).strip()
        if not cleaned_session_id:
            raise ValueError("session_id must not be empty")
        record = ActiveSessionRecord(
            session_id=cleaned_session_id,
            updated_at=_utc_now(),
        )
        self.path().write_text(
            json.dumps(asdict(record), indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        return record


def resolve_session_id(*, state_root: Path, session_id: str | None) -> Optional[str]:
    cleaned = str(session_id or "").strip()
    if cleaned:
        return cleaned
    return ActiveSessionStore(state_root).current_session_id()
