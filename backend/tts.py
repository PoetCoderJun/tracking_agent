from __future__ import annotations

import json
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from backend.actions import execute_speak
from backend.config import parse_dotenv
from backend.persistence import resolve_session_id
from backend.runner import commit_skill_turn
from backend.runtime_session import AgentSessionStore
from backend.skill_payload import processed_skill_payload, reply_session_result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_text(store: AgentSessionStore, session_id: str) -> str:
    session = store.load(session_id)
    history = list(session.session.get("conversation_history") or [])
    for entry in reversed(history):
        if str(entry.get("role", "")).strip() != "user":
            continue
        text = str(entry.get("text", "")).strip()
        if text:
            return text
    latest_text = str((session.latest_result or {}).get("text", "")).strip()
    return latest_text


def _tts_command(env_file: Path) -> list[str]:
    values = parse_dotenv(env_file)
    configured = str(values.get("ROBOT_TTS_COMMAND", "")).strip()
    return shlex.split(configured) if configured else []


def _mock_outbox_path(artifacts_root: Path) -> Path:
    return artifacts_root / "tts" / "mock_outbox.jsonl"


def _mock_tts(text: str, *, artifacts_root: Path) -> Dict[str, Any]:
    outbox_path = _mock_outbox_path(artifacts_root)
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    sent_at = _utc_now()
    with outbox_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "text": text,
                    "mode": "mock",
                    "sent_at": sent_at,
                },
                ensure_ascii=True,
            )
        )
        handle.write("\n")
    return {
        "mode": "mock",
        "configured": False,
        "command": [],
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "sent_at": sent_at,
        "outbox_path": str(outbox_path),
    }


def _real_tts(text: str, *, env_file: Path, artifacts_root: Path) -> Dict[str, Any]:
    command = _tts_command(env_file)
    if not command:
        return _mock_tts(text, artifacts_root=artifacts_root)
    result = execute_speak(text=text, command_prefix=command)
    return {
        "mode": "real",
        "configured": True,
        "command": list(result.argv),
        "returncode": int(result.returncode),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "sent_at": _utc_now(),
        "outbox_path": str(_mock_outbox_path(artifacts_root)),
    }


def _build_tts_payload(*, spoken_text: str, tool_output: Dict[str, Any]) -> Dict[str, Any]:
    return processed_skill_payload(
        skill_name="tts",
        session_result=reply_session_result(
            f"已播报：{spoken_text}",
            summary=f"tts: {spoken_text[:40]}",
            robot_response={"action": "speak", "text": spoken_text},
        ),
        tool="tts",
        tool_output=tool_output,
        skill_state_patch={
            "last_text": spoken_text,
            "last_mode": tool_output.get("mode"),
            "last_outbox_path": tool_output.get("outbox_path"),
            "last_sent_at": tool_output.get("sent_at"),
        },
    )


def _build_missing_text_payload() -> Dict[str, Any]:
    return processed_skill_payload(
        skill_name="tts",
        session_result=reply_session_result("当前没有可播报的文本。"),
        tool="tts",
        tool_output={"configured": False, "error": "missing text"},
    )


def run_tts_turn(
    *,
    text: str,
    session_id: str | None,
    state_root: Path,
    env_file: Path,
    artifacts_root: Path,
) -> Dict[str, Any]:
    resolved_session_id = resolve_session_id(state_root=state_root, session_id=session_id)
    sessions = AgentSessionStore(state_root=state_root)
    spoken_text = str(text).strip()
    if not spoken_text and resolved_session_id is not None:
        spoken_text = _default_text(sessions, resolved_session_id)

    payload = (
        _build_missing_text_payload()
        if not spoken_text
        else _build_tts_payload(
            spoken_text=spoken_text,
            tool_output=_real_tts(
                spoken_text,
                env_file=env_file,
                artifacts_root=artifacts_root,
            ),
        )
    )

    if resolved_session_id is None:
        return payload
    return commit_skill_turn(
        sessions=sessions,
        session_id=resolved_session_id,
        pi_payload=payload,
        env_file=env_file,
    )
