from __future__ import annotations

import argparse
import json
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from capabilities.actions import execute_speak
from agent.config import parse_dotenv
from agent.session_store import resolve_session_id
from agent.project_paths import resolve_project_path
from agent.session import AgentSession, AgentSessionStore
from agent.skill_payload import processed_skill_payload, reply_session_result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_text(session: AgentSession) -> str:
    if session.latest_user_text:
        return session.latest_user_text
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


def _build_tts_payload(
    *,
    spoken_text: str,
    tool_output: Dict[str, Any],
    request_id: str | None = None,
    request_function: str | None = None,
) -> Dict[str, Any]:
    session_result = {
        **reply_session_result(
            f"已播报：{spoken_text}",
            summary=f"tts: {spoken_text[:40]}",
            robot_response={"action": "speak", "text": spoken_text},
        )
    }
    if request_id not in (None, ""):
        session_result["request_id"] = str(request_id).strip()
    if request_function not in (None, ""):
        session_result["function"] = str(request_function).strip()
    return processed_skill_payload(
        skill_name="tts",
        session_result=session_result,
        tool="tts",
        tool_output=tool_output,
        skill_state_patch={
            "last_text": spoken_text,
            "last_mode": tool_output.get("mode"),
            "last_outbox_path": tool_output.get("outbox_path"),
            "last_sent_at": tool_output.get("sent_at"),
        },
    )


def _build_missing_text_payload(
    *,
    request_id: str | None = None,
    request_function: str | None = None,
) -> Dict[str, Any]:
    session_result = {
        **reply_session_result("当前没有可播报的文本。"),
    }
    if request_id not in (None, ""):
        session_result["request_id"] = str(request_id).strip()
    if request_function not in (None, ""):
        session_result["function"] = str(request_function).strip()
    return processed_skill_payload(
        skill_name="tts",
        session_result=session_result,
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
    bound_session: AgentSession | None = None,
    request_id: str | None = None,
    stale_guard: Callable[[str], None] | None = None,
) -> Dict[str, Any]:
    session = bound_session
    if session is None:
        resolved_session_id = resolve_session_id(state_root=state_root, session_id=session_id)
        if resolved_session_id is not None:
            session = AgentSessionStore(state_root=state_root).load(resolved_session_id)
    spoken_text = str(text).strip()
    if not spoken_text and session is not None:
        spoken_text = _default_text(session)

    request_function = None if session is None else str(session.session.get("latest_request_function") or "chat").strip()

    if not spoken_text:
        return _build_missing_text_payload(
            request_id=request_id,
            request_function=request_function,
        )

    if stale_guard is not None:
        stale_guard("before_tts_effect")
    return _build_tts_payload(
        spoken_text=spoken_text,
        tool_output=_real_tts(
            spoken_text,
            env_file=env_file,
            artifacts_root=artifacts_root,
        ),
        request_id=request_id,
        request_function=request_function,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one deterministic TTS skill turn.")
    parser.add_argument("--text", default="")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--state-root", default="./.runtime/agent-runtime")
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--artifacts-root", default="./.runtime/pi-agent")
    args = parser.parse_args(argv)

    payload = run_tts_turn(
        text=str(args.text),
        session_id=args.session_id,
        state_root=resolve_project_path(args.state_root),
        env_file=resolve_project_path(args.env_file),
        artifacts_root=resolve_project_path(args.artifacts_root),
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
