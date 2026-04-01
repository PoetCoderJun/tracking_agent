#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agent.runner import (
    _apply_tracking_rewrite_output,
    _tracking_rewrite_job_is_latest,
    _tracking_rewrite_status_payload,
    _update_latest_tracking_rewrite_state,
    _write_tracking_rewrite_json,
)
from backend.agent.runtime import LocalAgentRuntime
from skills.tracking.scripts.rewrite_memory import execute_rewrite_memory_tool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run tracking memory rewrite in a detached worker.")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--memory-file", required=True)
    parser.add_argument("--task", choices=("init", "update"), required=True)
    parser.add_argument("--crop-path", required=True)
    parser.add_argument("--frame-path", action="append", dest="frame_paths", default=[])
    parser.add_argument("--frame-id", required=True)
    parser.add_argument("--target-id", type=int, required=True)
    parser.add_argument("--env-file", default=".ENV")
    return parser.parse_args()


def _status_paths(job_dir: Path) -> tuple[Path, Path]:
    return job_dir / "status.json", job_dir / "result.json"


def _record_status(
    runtime: LocalAgentRuntime,
    *,
    job_id: str,
    job_dir: Path,
    session_id: str,
    status: str,
    task: str,
    frame_id: str,
    target_id: int,
    crop_path: str,
    frame_paths: list[str],
    requested_at: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    exit_code: int | None = None,
    reason: str | None = None,
    error: str | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    result_path: Path | None = None,
    pid: int | None = None,
) -> None:
    status_path, _ = _status_paths(job_dir)
    _write_tracking_rewrite_json(
        status_path,
        _tracking_rewrite_status_payload(
            job_id=job_id,
            session_id=session_id,
            status=status,
            task=task,
            frame_id=frame_id,
            target_id=target_id,
            crop_path=crop_path,
            frame_paths=frame_paths,
            requested_at=requested_at,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=exit_code,
            reason=reason,
            error=error,
            stdout_path=None if stdout_path is None else str(stdout_path),
            stderr_path=None if stderr_path is None else str(stderr_path),
            result_path=None if result_path is None else str(result_path),
            pid=pid,
        ),
    )
    _update_latest_tracking_rewrite_state(
        runtime,
        session_id=session_id,
        job_id=job_id,
        status=status,
        task=task,
        log_dir=job_dir,
        status_path=status_path,
        requested_at=requested_at,
        completed_at=completed_at,
        reason=reason,
        error=error,
        result_path=result_path,
        pid=pid,
    )


def _rewrite_still_relevant(
    runtime: LocalAgentRuntime,
    *,
    session_id: str,
    target_id: int,
    confirmed_frame_path: str,
) -> bool:
    context = runtime.context(session_id)
    tracking_state = dict(context.skill_cache.get("tracking") or {})
    current_target_id = tracking_state.get("latest_target_id")
    if current_target_id in (None, ""):
        return False
    current_frame_path = str(tracking_state.get("latest_confirmed_frame_path", "") or "").strip()
    return int(current_target_id) == int(target_id) and current_frame_path == confirmed_frame_path


def main() -> int:
    args = parse_args()
    runtime = LocalAgentRuntime(state_root=Path(args.state_root))
    job_dir = Path(args.job_dir)
    status_path, result_path = _status_paths(job_dir)
    stdout_path = job_dir / "stdout.log"
    stderr_path = job_dir / "stderr.log"
    frame_paths = [str(path).strip() for path in list(args.frame_paths or []) if str(path).strip()]
    if not frame_paths:
        completed_at = datetime.now(timezone.utc).isoformat()
        _record_status(
            runtime,
            job_id=args.job_id,
            job_dir=job_dir,
            session_id=args.session_id,
            status="failed",
            task=args.task,
            frame_id=args.frame_id,
            target_id=int(args.target_id),
            crop_path=str(args.crop_path),
            frame_paths=frame_paths,
            completed_at=completed_at,
            exit_code=1,
            error="rewrite_memory requires at least one frame path",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        return 0

    requested_at = None
    if status_path.exists():
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        value = payload.get("requested_at")
        if value not in (None, ""):
            requested_at = str(value)

    started_at = None
    if not _tracking_rewrite_job_is_latest(runtime, session_id=args.session_id, job_id=args.job_id):
        completed_at = datetime.now(timezone.utc).isoformat()
        _record_status(
            runtime,
            job_id=args.job_id,
            job_dir=job_dir,
            session_id=args.session_id,
            status="skipped",
            task=args.task,
            frame_id=args.frame_id,
            target_id=int(args.target_id),
            crop_path=str(args.crop_path),
            frame_paths=frame_paths,
            requested_at=requested_at,
            completed_at=completed_at,
            exit_code=0,
            reason="superseded",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        return 0

    started_at = datetime.now(timezone.utc).isoformat()
    _record_status(
        runtime,
        job_id=args.job_id,
        job_dir=job_dir,
        session_id=args.session_id,
        status="running",
        task=args.task,
        frame_id=args.frame_id,
        target_id=int(args.target_id),
        crop_path=str(args.crop_path),
        frame_paths=frame_paths,
        requested_at=requested_at,
        started_at=started_at,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        pid=os.getpid(),
    )

    confirmed_frame_path = frame_paths[-1]
    if not _rewrite_still_relevant(
        runtime,
        session_id=args.session_id,
        target_id=int(args.target_id),
        confirmed_frame_path=confirmed_frame_path,
    ):
        completed_at = datetime.now(timezone.utc).isoformat()
        _record_status(
            runtime,
            job_id=args.job_id,
            job_dir=job_dir,
            session_id=args.session_id,
            status="skipped",
            task=args.task,
            frame_id=args.frame_id,
            target_id=int(args.target_id),
            crop_path=str(args.crop_path),
            frame_paths=frame_paths,
            requested_at=requested_at,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=0,
            reason="stale_context",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            pid=os.getpid(),
        )
        return 0

    try:
        rewrite_output = execute_rewrite_memory_tool(
            memory_file=Path(args.memory_file),
            arguments={
                "task": args.task,
                "crop_path": args.crop_path,
                "frame_paths": frame_paths,
                "frame_id": args.frame_id,
                "target_id": int(args.target_id),
            },
            env_file=Path(args.env_file),
        )
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        completed_at = datetime.now(timezone.utc).isoformat()
        _record_status(
            runtime,
            job_id=args.job_id,
            job_dir=job_dir,
            session_id=args.session_id,
            status="failed",
            task=args.task,
            frame_id=args.frame_id,
            target_id=int(args.target_id),
            crop_path=str(args.crop_path),
            frame_paths=frame_paths,
            requested_at=requested_at,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=1,
            error=str(exc),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            pid=os.getpid(),
        )
        return 0

    if not _tracking_rewrite_job_is_latest(runtime, session_id=args.session_id, job_id=args.job_id):
        completed_at = datetime.now(timezone.utc).isoformat()
        _record_status(
            runtime,
            job_id=args.job_id,
            job_dir=job_dir,
            session_id=args.session_id,
            status="skipped",
            task=args.task,
            frame_id=args.frame_id,
            target_id=int(args.target_id),
            crop_path=str(args.crop_path),
            frame_paths=frame_paths,
            requested_at=requested_at,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=0,
            reason="superseded",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        return 0

    if not _rewrite_still_relevant(
        runtime,
        session_id=args.session_id,
        target_id=int(args.target_id),
        confirmed_frame_path=confirmed_frame_path,
    ):
        completed_at = datetime.now(timezone.utc).isoformat()
        _record_status(
            runtime,
            job_id=args.job_id,
            job_dir=job_dir,
            session_id=args.session_id,
            status="skipped",
            task=args.task,
            frame_id=args.frame_id,
            target_id=int(args.target_id),
            crop_path=str(args.crop_path),
            frame_paths=frame_paths,
            requested_at=requested_at,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=0,
            reason="stale_context",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        return 0

    _write_tracking_rewrite_json(result_path, rewrite_output)
    _apply_tracking_rewrite_output(
        runtime=runtime,
        session_id=args.session_id,
        rewrite_output=rewrite_output,
    )
    completed_at = datetime.now(timezone.utc).isoformat()
    _record_status(
        runtime,
        job_id=args.job_id,
        job_dir=job_dir,
        session_id=args.session_id,
        status="succeeded",
        task=args.task,
        frame_id=args.frame_id,
        target_id=int(args.target_id),
        crop_path=str(args.crop_path),
        frame_paths=frame_paths,
        requested_at=requested_at,
        started_at=started_at,
        completed_at=completed_at,
        exit_code=0,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        result_path=result_path,
        pid=os.getpid(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
