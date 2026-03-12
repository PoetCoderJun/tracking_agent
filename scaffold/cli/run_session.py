#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.config import load_settings
from tracking_agent.dashscope_client import DashScopeVisionClient
from tracking_agent.dashscope_tracking_backend import DashScopeTrackingBackend
from tracking_agent.dry_run_tracking_backend import DryRunTrackingBackend
from tracking_agent.core import PiAgentSessionLoop, SessionStore
from tracking_agent.memory_format import extract_memory_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the scaffolded Pi Agent tracking session loop.")
    parser.add_argument("--query-plan", required=True, help="Path to query_plan.json")
    parser.add_argument("--sessions-root", required=True, help="Directory to store session state")
    parser.add_argument("--session-id", default="default", help="Tracking session identifier")
    parser.add_argument("--env-file", default=".ENV", help="Path to .ENV for live DashScope config")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use the built-in dry-run backend instead of calling DashScope.",
    )
    parser.add_argument(
        "--message",
        action="append",
        default=[],
        help="Process one user message. Repeat to simulate multiple turns non-interactively.",
    )
    parser.add_argument(
        "--show-memory",
        action="store_true",
        help="Attach the latest normalized tracking memory to each JSON output line.",
    )
    return parser.parse_args()


def _build_loop(args: argparse.Namespace) -> PiAgentSessionLoop:
    store = SessionStore(Path(args.sessions_root))
    if args.dry_run:
        backend = DryRunTrackingBackend()
    else:
        settings = load_settings(Path(args.env_file))
        backend = DashScopeTrackingBackend(
            DashScopeVisionClient(settings),
            main_model=settings.main_model,
            sub_model=settings.sub_model,
        )
    return PiAgentSessionLoop(
        session_id=args.session_id,
        query_plan_path=Path(args.query_plan),
        store=store,
        backend=backend,
    )


def _attach_memory_snapshot(
    result: dict,
    store: SessionStore,
    session_id: str,
    show_memory: bool,
) -> dict:
    if not show_memory:
        return result
    session_path = store.session_dir(session_id) / "session.json"
    if not session_path.exists():
        return result
    memory_markdown = store.read_memory(session_id)
    return {
        **result,
        "memory_markdown": memory_markdown,
        "memory_text": extract_memory_text(memory_markdown),
    }


def _print_result(result) -> None:
    print(json.dumps(result, ensure_ascii=False))


def main() -> int:
    args = parse_args()
    store = SessionStore(Path(args.sessions_root))
    loop = _build_loop(args)

    if args.message:
        for message in args.message:
            result = loop.process_user_message(message)
            _print_result(
                _attach_memory_snapshot(
                    result=result,
                    store=store,
                    session_id=args.session_id,
                    show_memory=args.show_memory,
                )
            )
        return 0

    while True:
        try:
            user_input = input("pi-agent> ").strip()
        except EOFError:
            break
        if not user_input:
            continue
        if user_input in {"退出", "quit", "exit"}:
            break
        result = loop.process_user_message(user_input)
        _print_result(
            _attach_memory_snapshot(
                result=result,
                store=store,
                session_id=args.session_id,
                show_memory=args.show_memory,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
