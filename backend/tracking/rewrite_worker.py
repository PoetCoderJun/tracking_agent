#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.session_store import AgentSessionStore
from backend.tracking.deterministic import apply_tracking_rewrite_output
from backend.tracking.rewrite_memory import execute_rewrite_memory_tool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run tracking memory rewrite in a detached worker.")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--session-file", required=True)
    parser.add_argument("--task", choices=("init", "update"), required=True)
    parser.add_argument("--crop-path", required=True)
    parser.add_argument("--frame-path", action="append", dest="frame_paths", default=[])
    parser.add_argument("--frame-id", required=True)
    parser.add_argument("--target-id", type=int, required=True)
    parser.add_argument("--confirmation-reason", default="")
    parser.add_argument("--candidate-checks-json", default="")
    parser.add_argument("--env-file", default=".ENV")
    return parser.parse_args()


def _rewrite_still_relevant(
    sessions: AgentSessionStore,
    *,
    session_id: str,
    target_id: int,
    confirmed_frame_path: str,
) -> bool:
    session = sessions.load(session_id)
    tracking_state = dict(session.skills.get("tracking") or {})
    current_target_id = tracking_state.get("latest_target_id")
    if current_target_id in (None, ""):
        return False
    current_frame_path = str(tracking_state.get("latest_confirmed_frame_path", "") or "").strip()
    return int(current_target_id) == int(target_id) and current_frame_path == confirmed_frame_path


def main() -> int:
    args = parse_args()
    sessions = AgentSessionStore(state_root=Path(args.state_root))
    frame_paths = [str(path).strip() for path in list(args.frame_paths or []) if str(path).strip()]
    if not frame_paths:
        return 1

    confirmed_frame_path = frame_paths[-1]
    if not _rewrite_still_relevant(
        sessions,
        session_id=args.session_id,
        target_id=int(args.target_id),
        confirmed_frame_path=confirmed_frame_path,
    ):
        return 0

    try:
        rewrite_output = execute_rewrite_memory_tool(
            session_file=Path(args.session_file),
            arguments={
                "task": args.task,
                "crop_path": args.crop_path,
                "frame_paths": frame_paths,
                "frame_id": args.frame_id,
                "target_id": int(args.target_id),
                "confirmation_reason": args.confirmation_reason,
                "candidate_checks": args.candidate_checks_json,
            },
            env_file=Path(args.env_file),
        )
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1

    if not _rewrite_still_relevant(
        sessions,
        session_id=args.session_id,
        target_id=int(args.target_id),
        confirmed_frame_path=confirmed_frame_path,
    ):
        return 0

    apply_tracking_rewrite_output(
        sessions=sessions,
        session_id=args.session_id,
        rewrite_output=rewrite_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
