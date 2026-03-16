#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SKILL_SCRIPTS_DIR = ROOT / "skills" / "vision-tracking-skill" / "scripts"
if str(SKILL_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS_DIR))

import pi_agent_adapter as adapter
import pi_backend_bridge as bridge


@dataclass(frozen=True)
class ToolRequest:
    tool_name: str
    arguments: Dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a lightweight host agent loop that auto-processes new robot frames."
    )
    parser.add_argument("--backend-base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument(
        "--reconnect-seconds",
        type=float,
        default=None,
        help="Reconnect delay for the websocket session event stream. Defaults to --poll-seconds for compatibility.",
    )
    parser.add_argument("--ongoing-text", default="持续跟踪")
    parser.add_argument("--env-file", default=".ENV")
    parser.add_argument("--config-path", default=str(adapter.DEFAULT_CONFIG_PATH))
    parser.add_argument("--artifacts-root", default="./runtime/pi-agent")
    parser.add_argument("--skip-rewrite-memory", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def _optional_text(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _latest_frame_id(raw_session: Dict[str, Any]) -> Optional[str]:
    frames = raw_session.get("recent_frames") or []
    if not frames:
        return None
    return _optional_text(frames[-1].get("frame_id"))


def _latest_result_frame_id(raw_session: Dict[str, Any]) -> Optional[str]:
    latest_result = raw_session.get("latest_result") or {}
    return _optional_text(latest_result.get("frame_id"))


def latest_user_text(raw_session: Dict[str, Any]) -> Optional[str]:
    history = raw_session.get("conversation_history") or []
    for entry in reversed(history):
        if str(entry.get("role", "")).strip() != "user":
            continue
        text = _optional_text(entry.get("text"))
        if text:
            return text
    return None


def session_has_active_target(raw_session: Dict[str, Any]) -> bool:
    return bool(
        raw_session.get("latest_target_id") is not None
        and _optional_text(raw_session.get("latest_confirmed_frame_path"))
    )


def is_ongoing_text(text: Optional[str], ongoing_text: str) -> bool:
    normalized_text = _optional_text(text)
    normalized_ongoing = _optional_text(ongoing_text)
    if normalized_text is None or normalized_ongoing is None:
        return False
    return normalized_text == normalized_ongoing


def session_needs_processing(raw_session: Dict[str, Any]) -> bool:
    latest_frame_id = _latest_frame_id(raw_session)
    if latest_frame_id is None:
        return False
    return latest_frame_id != _latest_result_frame_id(raw_session)


def select_tool_request(raw_session: Dict[str, Any], ongoing_text: str) -> Optional[ToolRequest]:
    if not session_needs_processing(raw_session):
        return None

    latest_user = latest_user_text(raw_session)
    pending_question = _optional_text(raw_session.get("pending_question"))

    if pending_question and is_ongoing_text(latest_user, ongoing_text):
        return ToolRequest(
            tool_name="reply",
            arguments={
                "text": pending_question,
                "needs_clarification": True,
                "clarification_question": pending_question,
            },
        )

    if not session_has_active_target(raw_session):
        target_description = latest_user or _optional_text(raw_session.get("target_description"))
        if not target_description or is_ongoing_text(target_description, ongoing_text):
            clarification = pending_question or "请再描述一下你要跟踪的人。"
            return ToolRequest(
                tool_name="reply",
                arguments={
                    "text": clarification,
                    "needs_clarification": True,
                    "clarification_question": clarification,
                },
            )
        return ToolRequest(
            tool_name="init",
            arguments={"target_description": target_description},
        )

    return ToolRequest(
        tool_name="track",
        arguments={"user_text": latest_user or ongoing_text},
    )


def build_session_url(backend_base_url: str, session_id: str) -> str:
    return bridge.build_session_url(backend_base_url, session_id, "")


def build_session_events_url(backend_base_url: str) -> str:
    parsed = urlsplit(backend_base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, parsed.netloc, f"{path}/ws/session-events", "", ""))


def reconnect_delay_seconds(args: argparse.Namespace) -> float:
    if args.reconnect_seconds is not None:
        return args.reconnect_seconds
    return args.poll_seconds


def list_session_ids(backend_base_url: str) -> List[str]:
    payload = bridge.fetch_json(f"{backend_base_url.rstrip('/')}/api/v1/sessions")
    sessions = payload.get("sessions", [])
    return [
        str(item["session_id"])
        for item in sessions
        if _optional_text(item.get("session_id"))
    ]


def process_session(
    *,
    backend_base_url: str,
    session_id: str,
    ongoing_text: str,
    env_file: Path,
    config_path: Path,
    artifacts_root: Path,
    skip_rewrite_memory: bool,
) -> Dict[str, Any]:
    raw_session = bridge.fetch_json(build_session_url(backend_base_url, session_id))
    tool_request = select_tool_request(raw_session, ongoing_text=ongoing_text)
    latest_frame_id = _latest_frame_id(raw_session)
    if tool_request is None:
        return {
            "session_id": session_id,
            "frame_id": latest_frame_id,
            "status": "idle",
        }

    result = bridge.run_bridge(
        backend_base_url=backend_base_url,
        session_id=session_id,
        tool_name=tool_request.tool_name,
        arguments=tool_request.arguments,
        env_file=env_file,
        config_path=config_path,
        artifacts_root=artifacts_root,
        skip_rewrite_memory=skip_rewrite_memory,
        dry_run=False,
    )
    tool_output = result.get("tool_output") or {}
    return {
        "session_id": session_id,
        "frame_id": latest_frame_id,
        "status": "processed",
        "tool": tool_request.tool_name,
        "found": tool_output.get("found"),
        "needs_clarification": tool_output.get("needs_clarification"),
        "text": tool_output.get("text"),
    }


def iter_target_session_ids(backend_base_url: str, session_id: Optional[str]) -> Iterable[str]:
    if session_id:
        return [session_id]
    return list_session_ids(backend_base_url)


def session_ids_from_event(event: Dict[str, Any], selected_session_id: Optional[str]) -> List[str]:
    event_type = _optional_text(event.get("type"))
    session_ids: List[str] = []

    if event_type == "dashboard_state":
        session_ids = [
            str(item["session_id"])
            for item in event.get("sessions", [])
            if _optional_text(item.get("session_id"))
        ]
    elif event_type == "session_update":
        changed_session_id = _optional_text(event.get("changed_session_id")) or _optional_text(event.get("session_id"))
        if changed_session_id:
            session_ids = [changed_session_id]

    if selected_session_id:
        session_ids = [session_id for session_id in session_ids if session_id == selected_session_id]

    unique_session_ids: List[str] = []
    seen: set[str] = set()
    for session_id in session_ids:
        if session_id in seen:
            continue
        seen.add(session_id)
        unique_session_ids.append(session_id)
    return unique_session_ids


def _load_websocket_connect():
    try:
        from websockets.client import connect
    except ImportError as exc:  # pragma: no cover - dependency errors are environment-specific
        raise RuntimeError(
            "Missing websocket client dependency. Install the 'websockets' package before running run_host_agent.py."
        ) from exc
    return connect


async def iter_session_events(backend_base_url: str) -> Iterable[Dict[str, Any]]:
    connect = _load_websocket_connect()
    events_url = build_session_events_url(backend_base_url)
    async with connect(events_url, open_timeout=30, ping_interval=20, ping_timeout=30, max_size=None) as websocket:
        async for message in websocket:
            payload = json.loads(message)
            if isinstance(payload, dict):
                yield payload


async def _async_main() -> int:
    args = parse_args()
    reconnect_delay = reconnect_delay_seconds(args)
    if reconnect_delay <= 0:
        raise ValueError("Reconnect delay must be positive")

    env_file = Path(args.env_file)
    config_path = Path(args.config_path)
    artifacts_root = Path(args.artifacts_root)

    try:
        while True:
            try:
                async for event in iter_session_events(args.backend_base_url):
                    for session_id in session_ids_from_event(event, args.session_id):
                        try:
                            outcome = await asyncio.to_thread(
                                process_session,
                                backend_base_url=args.backend_base_url,
                                session_id=session_id,
                                ongoing_text=args.ongoing_text,
                                env_file=env_file,
                                config_path=config_path,
                                artifacts_root=artifacts_root,
                                skip_rewrite_memory=args.skip_rewrite_memory,
                            )
                        except Exception as exc:
                            print(
                                json.dumps(
                                    {
                                        "session_id": session_id,
                                        "status": "error",
                                        "error": str(exc),
                                    },
                                    ensure_ascii=False,
                                ),
                                file=sys.stderr,
                                flush=True,
                            )
                            continue

                        if outcome["status"] == "processed":
                            print(json.dumps(outcome, ensure_ascii=False), flush=True)

                    if args.once and _optional_text(event.get("type")) == "dashboard_state":
                        return 0
            except Exception as exc:
                print(
                    json.dumps(
                        {
                            "status": "error",
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                if args.once:
                    return 1
                await asyncio.sleep(reconnect_delay)
    except KeyboardInterrupt:
        return 0


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    raise SystemExit(main())
