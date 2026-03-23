#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SKILL_SCRIPTS_DIR = ROOT / "skills" / "vision-tracking-skill" / "scripts"
if str(SKILL_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS_DIR))

import pi_agent_adapter as adapter
import pi_backend_bridge as bridge
from tracking_agent.service_urls import build_backend_service_url


ToolRequest = adapter.ToolRequest


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
    return adapter.optional_text(value)


def _latest_frame_id(raw_session: Dict[str, Any]) -> Optional[str]:
    return adapter.latest_frame_id(raw_session)


def _latest_request_id(raw_session: Dict[str, Any]) -> Optional[str]:
    return adapter.latest_request_id(raw_session)


def _latest_request_function(raw_session: Dict[str, Any]) -> Optional[str]:
    return adapter.latest_request_function(raw_session)


def _latest_result_frame_id(raw_session: Dict[str, Any]) -> Optional[str]:
    return adapter.latest_result_frame_id(raw_session)


def _latest_result_request_id(raw_session: Dict[str, Any]) -> Optional[str]:
    return adapter.latest_result_request_id(raw_session)


def latest_user_text(raw_session: Dict[str, Any]) -> Optional[str]:
    return adapter.latest_user_text(raw_session)


def session_has_active_target(raw_session: Dict[str, Any]) -> bool:
    return adapter.session_has_active_target(raw_session)


def is_ongoing_text(text: Optional[str], ongoing_text: str) -> bool:
    return adapter.is_ongoing_text(text, ongoing_text)


def is_explicit_init_text(text: Optional[str], ongoing_text: str) -> bool:
    return adapter.is_explicit_init_text(text, ongoing_text)


def is_reset_context_text(text: Optional[str]) -> bool:
    return adapter.is_reset_context_text(text)


def session_needs_processing(raw_session: Dict[str, Any]) -> bool:
    return adapter.session_needs_processing(raw_session)


def select_tool_request(raw_session: Dict[str, Any], ongoing_text: str) -> Optional[ToolRequest]:
    return adapter.select_tool_request(raw_session, ongoing_text)


def build_session_url(backend_base_url: str, session_id: str) -> str:
    return bridge.build_session_url(backend_base_url, session_id, "")


def build_session_events_url(backend_base_url: str) -> str:
    return build_backend_service_url(backend_base_url, channel="session_events")


def reconnect_delay_seconds(args: argparse.Namespace) -> float:
    if args.reconnect_seconds is not None:
        return args.reconnect_seconds
    return args.poll_seconds


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

    if tool_request.tool_name == "reset_context":
        reset_result = bridge.post_json(
            bridge.build_session_url(backend_base_url, session_id, "reset-context"),
            {},
        )
        return {
            "session_id": session_id,
            "frame_id": latest_frame_id,
            "status": "processed",
            "tool": tool_request.tool_name,
            "found": False,
            "needs_clarification": False,
            "text": (reset_result.get("latest_result") or {}).get("text"),
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
    backend_base_url = normalize_base_url(args.backend_base_url)

    try:
        while True:
            try:
                async for event in iter_session_events(backend_base_url):
                    for session_id in session_ids_from_event(event, args.session_id):
                        try:
                            outcome = await asyncio.to_thread(
                                process_session,
                                backend_base_url=backend_base_url,
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
