from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from tracking_agent.core.intent_router import classify_user_intent
from tracking_agent.core.pi_agent_core import PiAgentCore, TrackingBackend
from tracking_agent.core.session_store import SessionStore, TrackingSession
from tracking_agent.history_queue import get_query_batch, load_query_plan


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


class PiAgentSessionLoop:
    def __init__(
        self,
        session_id: str,
        query_plan_path: Path,
        store: SessionStore,
        backend: TrackingBackend,
    ):
        self._session_id = session_id
        self._query_plan_path = query_plan_path
        self._store = store
        self._core = PiAgentCore(store=store, backend=backend)
        self._query_plan = load_query_plan(query_plan_path)
        self._batches = self._query_plan.get("batches", [])
        if not self._batches:
            raise ValueError(f"Query plan has no batches: {query_plan_path}")
        self._ensure_runtime_state()

    def process_user_message(self, text: str) -> Dict[str, Any]:
        raw_text = text.strip()
        has_session = self._session_exists()
        session = self._try_load_session()
        intent = self._resolve_intent(raw_text, has_session, session)

        if intent == "no_session":
            return {
                "intent": "no_session",
                "message": "当前还没有 active tracking session。请先描述你要跟踪的人。",
            }

        if intent in {"initialize_target", "replace_target"}:
            batch = self._current_context_batch()
            target_description = self._extract_target_description(raw_text)
            result = (
                self._core.replace_target(
                    session_id=self._session_id,
                    target_description=target_description,
                    frame_paths=self._frame_paths_from_batch(batch),
                )
                if has_session and intent == "replace_target"
                else self._core.initialize_target(
                    session_id=self._session_id,
                    target_description=target_description,
                    frame_paths=self._frame_paths_from_batch(batch),
                )
            )
            self._update_runtime_after_reuse(batch["batch_index"])
            return {
                "intent": intent,
                "batch": self._batch_summary(batch),
                "session": result["session"],
                "memory": result["memory"],
                "message": f"已{'重新' if intent == 'replace_target' else ''}初始化跟踪目标。",
            }

        if intent == "continue_tracking":
            batch = self._next_tracking_batch()
            if batch is None:
                state = self.get_runtime_state()
                return {
                    "intent": intent,
                    "message": "没有更多 query batch 可以继续处理了。",
                    "runtime_state": state,
                }
            result = self._core.run_tracking_step(
                session_id=self._session_id,
                frame_paths=self._latest_frame_from_batch(batch),
                recovery_frame_paths=self._frame_paths_from_batch(batch),
            )
            self._advance_runtime(batch["batch_index"])
            return {
                "intent": intent,
                "batch": self._batch_summary(batch),
                "session": result["session"],
                "locate_result": result["locate_result"],
                "memory": result["memory"],
            }

        if intent == "clarify_target":
            batch = self._current_context_batch()
            session = self._store.load_session(self._session_id)
            self._core.add_clarification(session_id=self._session_id, note=raw_text)
            result = self._core.run_tracking_step(
                session_id=self._session_id,
                frame_paths=self._latest_frame_from_batch(batch),
                recovery_frame_paths=(
                    self._frame_paths_from_batch(batch)
                    if session.status == "missing"
                    else None
                ),
            )
            self._update_runtime_after_reuse(batch["batch_index"])
            return {
                "intent": intent,
                "batch": self._batch_summary(batch),
                "session": result["session"],
                "locate_result": result["locate_result"],
                "memory": result["memory"],
            }

        if intent in {"ask_whereabouts", "ask_tracking_status", "chat"}:
            batch = self._current_context_batch()
            result = self._core.answer_chat(
                session_id=self._session_id,
                question=raw_text,
                frame_paths=self._latest_frame_from_batch(batch),
            )
            return {
                "intent": intent,
                "batch": self._batch_summary(batch),
                "session": result["session"],
                "answer": result["answer"],
            }

        return {
            "intent": intent,
            "message": f"暂未处理的 intent: {intent}",
        }

    def get_runtime_state(self) -> Dict[str, Any]:
        return asdict(self._load_runtime_state())

    def _resolve_intent(
        self,
        text: str,
        has_session: bool,
        session: Optional[TrackingSession],
    ) -> str:
        base_intent = classify_user_intent(text, has_active_session=has_session)

        if not has_session:
            if base_intent == "initialize_target":
                return base_intent
            if base_intent in {"ask_whereabouts", "ask_tracking_status", "continue_tracking", "clarify_target"}:
                return "no_session"
            return "initialize_target" if text else "no_session"

        lowered = text.lower()
        if (
            base_intent == "chat"
            and any(marker in lowered for marker in ("跟踪", "track", "定位"))
        ):
            return "replace_target"

        if session and session.status == "clarifying" and base_intent == "chat":
            return "clarify_target"

        return base_intent

    def _extract_target_description(self, text: str) -> str:
        cleaned = text.strip()
        prefixes = [
            "换一个目标，跟踪",
            "换一个目标",
            "换目标，跟踪",
            "换目标",
            "帮我跟踪",
            "请跟踪",
            "重新初始化为",
            "重新初始化",
            "重新跟踪",
            "跟踪",
            "track",
            "定位",
        ]
        lowered = cleaned.lower()
        for prefix in prefixes:
            if lowered.startswith(prefix.lower()):
                cleaned = cleaned[len(prefix):].strip(" ，。,.：:;；")
                break
        return cleaned or text.strip()

    def _frame_paths_from_batch(self, batch: Dict[str, Any]):
        return [Path(frame["path"]) for frame in batch.get("frames", [])]

    def _latest_frame_from_batch(self, batch: Dict[str, Any]):
        frame_paths = self._frame_paths_from_batch(batch)
        return frame_paths[-1:] if frame_paths else []

    def _batch_summary(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "batch_index": batch["batch_index"],
            "query_time_seconds": batch["query_time_seconds"],
            "frame_count": len(batch.get("frames", [])),
        }

    def _current_context_batch(self) -> Dict[str, Any]:
        state = self._load_runtime_state()
        batch_index = state.last_batch_index if state.last_batch_index is not None else 0
        return get_query_batch(self._query_plan_path, batch_index)

    def _next_tracking_batch(self) -> Optional[Dict[str, Any]]:
        state = self._load_runtime_state()
        if state.next_batch_index >= state.total_batches:
            return None
        return get_query_batch(self._query_plan_path, state.next_batch_index)

    def _advance_runtime(self, batch_index: int) -> None:
        state = self._load_runtime_state()
        updated = RuntimeState(
            session_id=state.session_id,
            query_plan_path=state.query_plan_path,
            next_batch_index=max(state.next_batch_index, batch_index + 1),
            last_batch_index=batch_index,
            total_batches=state.total_batches,
            updated_at=_utc_now(),
        )
        self._write_runtime_state(updated)

    def _update_runtime_after_reuse(self, batch_index: int) -> None:
        state = self._load_runtime_state()
        updated = RuntimeState(
            session_id=state.session_id,
            query_plan_path=state.query_plan_path,
            next_batch_index=max(state.next_batch_index, batch_index + 1),
            last_batch_index=batch_index,
            total_batches=state.total_batches,
            updated_at=_utc_now(),
        )
        self._write_runtime_state(updated)

    def _runtime_state_path(self) -> Path:
        session_dir = self._store.session_dir(self._session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / "runtime_state.json"

    def _ensure_runtime_state(self) -> None:
        state_path = self._runtime_state_path()
        if state_path.exists():
            return
        initial = RuntimeState(
            session_id=self._session_id,
            query_plan_path=str(self._query_plan_path),
            next_batch_index=0,
            last_batch_index=None,
            total_batches=len(self._batches),
            updated_at=_utc_now(),
        )
        self._write_runtime_state(initial)

    def _load_runtime_state(self) -> RuntimeState:
        payload = json.loads(self._runtime_state_path().read_text(encoding="utf-8"))
        return RuntimeState(**payload)

    def _write_runtime_state(self, state: RuntimeState) -> None:
        self._runtime_state_path().write_text(
            json.dumps(asdict(state), indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def _session_exists(self) -> bool:
        return (self._store.session_dir(self._session_id) / "session.json").exists()

    def _try_load_session(self) -> Optional[TrackingSession]:
        if not self._session_exists():
            return None
        return self._store.load_session(self._session_id)
