from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tracking_agent.core.session_store import SessionStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RuntimeState:
    session_id: str
    query_plan_path: str
    next_batch_index: int
    last_batch_index: Optional[int]
    total_batches: int
    updated_at: str


class RuntimeStateStore:
    def __init__(self, store: SessionStore, session_id: str):
        self._store = store
        self._session_id = session_id

    def path(self) -> Path:
        session_dir = self._store.session_dir(self._session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / "runtime_state.json"

    def ensure(self, query_plan_path: Path, total_batches: int) -> RuntimeState:
        existing = self.load_if_exists()
        if existing and (
            existing.query_plan_path == str(query_plan_path)
            and existing.total_batches == total_batches
        ):
            return existing

        initial = RuntimeState(
            session_id=self._session_id,
            query_plan_path=str(query_plan_path),
            next_batch_index=0,
            last_batch_index=None,
            total_batches=total_batches,
            updated_at=_utc_now(),
        )
        self.write(initial)
        return initial

    def load(self) -> RuntimeState:
        payload = json.loads(self.path().read_text(encoding="utf-8"))
        return RuntimeState(**payload)

    def load_if_exists(self) -> Optional[RuntimeState]:
        state_path = self.path()
        if not state_path.exists():
            return None
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        return RuntimeState(**payload)

    def write(self, state: RuntimeState) -> RuntimeState:
        self.path().write_text(
            json.dumps(asdict(state), indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        return state

    def advance(self, query_plan_path: Path, total_batches: int, batch_index: int) -> RuntimeState:
        state = self.ensure(query_plan_path=query_plan_path, total_batches=total_batches)
        updated = RuntimeState(
            session_id=state.session_id,
            query_plan_path=state.query_plan_path,
            next_batch_index=max(state.next_batch_index, batch_index + 1),
            last_batch_index=batch_index,
            total_batches=state.total_batches,
            updated_at=_utc_now(),
        )
        return self.write(updated)

    def reuse(self, query_plan_path: Path, total_batches: int, batch_index: int) -> RuntimeState:
        return self.advance(
            query_plan_path=query_plan_path,
            total_batches=total_batches,
            batch_index=batch_index,
        )
