#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.core import SessionStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect or update tracking session artifacts.")
    parser.add_argument("--sessions-root", required=True, help="Directory containing session folders")
    parser.add_argument("--session-id", required=True, help="Session identifier")
    parser.add_argument(
        "--action",
        choices=(
            "show",
            "artifacts-show",
            "create-or-reset",
            "write-memory",
            "write-latest-result",
            "update-status",
            "add-clarification",
            "add-reference-crop",
            "set-latest-visualization",
            "set-latest-confirmed-frame",
        ),
        default="show",
    )
    parser.add_argument("--show-memory", action="store_true")
    parser.add_argument("--target-description", default=None)
    parser.add_argument("--initial-memory", default="")
    parser.add_argument("--memory", default=None)
    parser.add_argument("--result-json", default=None)
    parser.add_argument("--status", default=None)
    parser.add_argument("--pending-question", default=None)
    parser.add_argument("--note", default=None)
    parser.add_argument("--crop-path", default=None)
    parser.add_argument("--visualization-path", default=None)
    parser.add_argument("--frame-path", default=None)
    return parser.parse_args()


def _print_session(store: SessionStore, session_id: str, show_memory: bool) -> None:
    session = store.load_session(session_id)
    payload = {"session": asdict(session)}
    if show_memory:
        payload["memory"] = store.read_memory(session_id)
    print(json.dumps(payload, ensure_ascii=False))


def _print_artifacts(store: SessionStore, session_id: str, show_memory: bool) -> None:
    session = store.load_session(session_id)
    payload = {
        "session_id": session.session_id,
        "status": session.status,
        "memory_path": session.memory_path,
        "latest_visualization_path": session.latest_visualization_path,
        "latest_result_path": session.latest_result_path,
    }
    if show_memory:
        payload["memory"] = store.read_memory(session_id)
    print(json.dumps(payload, ensure_ascii=False))


def main() -> int:
    args = parse_args()
    store = SessionStore(Path(args.sessions_root))

    if args.action == "show":
        _print_session(store, args.session_id, args.show_memory)
        return 0

    if args.action == "artifacts-show":
        _print_artifacts(store, args.session_id, args.show_memory)
        return 0

    if args.action == "create-or-reset":
        if args.target_description is None:
            raise ValueError("--target-description is required for create-or-reset")
        store.create_or_reset_session(
            session_id=args.session_id,
            target_description=args.target_description,
            initial_memory=args.initial_memory,
        )
        _print_session(store, args.session_id, args.show_memory)
        return 0

    if args.action == "write-memory":
        if args.memory is None:
            raise ValueError("--memory is required for write-memory")
        store.write_memory(args.session_id, args.memory)
        _print_session(store, args.session_id, args.show_memory)
        return 0

    if args.action == "write-latest-result":
        if args.result_json is None:
            raise ValueError("--result-json is required for write-latest-result")
        store.write_latest_result(args.session_id, json.loads(args.result_json))
        _print_session(store, args.session_id, args.show_memory)
        return 0

    if args.action == "update-status":
        if args.status is None:
            raise ValueError("--status is required for update-status")
        pending_question = args.pending_question if args.pending_question else None
        store.update_status(
            session_id=args.session_id,
            status=args.status,
            pending_clarification_question=pending_question,
        )
        _print_session(store, args.session_id, args.show_memory)
        return 0

    if args.action == "add-clarification":
        if args.note is None:
            raise ValueError("--note is required for add-clarification")
        store.add_clarification_note(args.session_id, args.note)
        _print_session(store, args.session_id, args.show_memory)
        return 0

    if args.action == "add-reference-crop":
        if args.crop_path is None:
            raise ValueError("--crop-path is required for add-reference-crop")
        store.add_reference_crop(args.session_id, Path(args.crop_path))
        _print_session(store, args.session_id, args.show_memory)
        return 0

    if args.action == "set-latest-visualization":
        if args.visualization_path is None:
            raise ValueError("--visualization-path is required for set-latest-visualization")
        store.set_latest_visualization_path(args.session_id, Path(args.visualization_path))
        _print_artifacts(store, args.session_id, args.show_memory)
        return 0

    if args.action == "set-latest-confirmed-frame":
        if args.frame_path is None:
            raise ValueError("--frame-path is required for set-latest-confirmed-frame")
        store.set_latest_confirmed_frame_path(args.session_id, Path(args.frame_path))
        _print_session(store, args.session_id, args.show_memory)
        return 0

    raise ValueError(f"Unsupported action: {args.action}")


if __name__ == "__main__":
    raise SystemExit(main())
