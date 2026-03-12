from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

from tracking_agent.frame_queue import extract_video_to_frame_queue
from tracking_agent.query_plan import build_query_batches, write_query_plan
from tracking_agent.target_crop import save_target_crop


def _update_reference_crop_bank(
    crop_bank: List[Path],
    crop_path: Path,
    max_crops: int = 3,
) -> List[Path]:
    existing = [path for path in crop_bank if str(path) != str(crop_path)]
    if not existing:
        updated = [crop_path]
    elif len(existing) == 1:
        updated = [existing[0], crop_path]
    elif len(existing) == 2:
        updated = [existing[0], existing[1], crop_path]
    else:
        updated = [existing[0], existing[-1], crop_path]
    return updated[-max_crops:]


@dataclass(frozen=True)
class BenchmarkRequest:
    stage: str
    batch_index: int
    duration_seconds: float
    query_time_seconds: float | None = None
    frame_count: int | None = None
    found: bool | None = None
    confidence: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class BenchmarkRun:
    query_interval_seconds: int
    recent_frame_count: int
    requests: List[BenchmarkRequest]


def prepare_query_plan_for_benchmark(
    video_path: Path,
    runtime_dir: Path,
    sample_fps: float,
    query_interval_seconds: int,
    recent_frame_count: int,
) -> Path:
    manifest = extract_video_to_frame_queue(
        video_path=video_path,
        runtime_dir=runtime_dir,
        sample_fps=sample_fps,
    )
    batches = build_query_batches(
        frames=manifest.frames,
        query_interval_seconds=query_interval_seconds,
        recent_frame_count=recent_frame_count,
    )
    return write_query_plan(
        runtime_dir=runtime_dir,
        batches=batches,
        query_interval_seconds=query_interval_seconds,
        recent_frame_count=recent_frame_count,
    )


def benchmark_tracking_run(
    backend,
    target_description: str,
    query_plan_path: Path,
    max_tracking_batches: int,
) -> BenchmarkRun:
    query_plan = json.loads(query_plan_path.read_text(encoding="utf-8"))
    batches: Sequence[Dict[str, Any]] = query_plan.get("batches", [])
    if not batches:
        raise ValueError(f"No batches found in query plan: {query_plan_path}")

    requests: List[BenchmarkRequest] = []
    init_batch = batches[0]
    init_frame_paths = [Path(frame["path"]) for frame in init_batch["frames"]]

    started = time.perf_counter()
    bootstrap_result = backend.bootstrap_target(
        target_description=target_description,
        frame_paths=init_frame_paths,
    )
    bootstrap_duration = time.perf_counter() - started
    crops_dir = query_plan_path.parent / "benchmark_reference_crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    crop_path = crops_dir / "target_crop_0000.jpg"
    save_target_crop(init_frame_paths[-1], bootstrap_result["bbox"], crop_path)
    last_confirmed_frame_paths = [init_frame_paths[-1]]
    memory = backend.initialize_memory(
        frame_paths=init_frame_paths,
        target_crop_path=crop_path,
        bootstrap_description=target_description,
    )
    requests.append(
        BenchmarkRequest(
            stage="init",
            batch_index=int(init_batch["batch_index"]),
            duration_seconds=round(time.perf_counter() - started, 3),
            query_time_seconds=float(init_batch["query_time_seconds"]),
            frame_count=len(init_frame_paths),
        )
    )
    requests.append(
        BenchmarkRequest(
            stage="bootstrap",
            batch_index=int(init_batch["batch_index"]),
            duration_seconds=round(bootstrap_duration, 3),
            query_time_seconds=float(init_batch["query_time_seconds"]),
            frame_count=len(init_frame_paths),
            found=bool(bootstrap_result.get("found")),
            confidence=float(bootstrap_result.get("confidence", 0.0)),
        )
    )

    for batch in batches[1 : 1 + max_tracking_batches]:
        frame_paths = [Path(frame["path"]) for frame in batch["frames"]]
        batch_index = int(batch["batch_index"])
        query_time = float(batch["query_time_seconds"])
        latest_frame_path = frame_paths[-1:]
        active_context = latest_frame_path

        started = time.perf_counter()
        locate_result = backend.locate_target(
            memory_markdown=memory,
            frame_paths=latest_frame_path,
            reference_frame_paths=last_confirmed_frame_paths,
        )
        locate_duration = round(time.perf_counter() - started, 3)
        requests.append(
            BenchmarkRequest(
                stage="locate",
                batch_index=batch_index,
                duration_seconds=locate_duration,
                query_time_seconds=query_time,
                frame_count=len(latest_frame_path),
                found=bool(locate_result.get("found")),
                confidence=float(locate_result.get("confidence", 0.0)),
            )
        )

        if not locate_result.get("found") and not locate_result.get("needs_clarification"):
            started = time.perf_counter()
            locate_result = backend.locate_target(
                memory_markdown=memory,
                frame_paths=frame_paths,
                reference_frame_paths=last_confirmed_frame_paths,
            )
            recovery_duration = round(time.perf_counter() - started, 3)
            active_context = frame_paths
            requests.append(
                BenchmarkRequest(
                    stage="locate_recovery",
                    batch_index=batch_index,
                    duration_seconds=recovery_duration,
                    query_time_seconds=query_time,
                    frame_count=len(frame_paths),
                    found=bool(locate_result.get("found")),
                    confidence=float(locate_result.get("confidence", 0.0)),
                )
            )

        if locate_result.get("found") and locate_result.get("bbox") is not None:
            crop_path = crops_dir / f"target_crop_{batch_index:04d}.jpg"
            save_target_crop(active_context[-1], locate_result["bbox"], crop_path)
            last_confirmed_frame_paths = [active_context[-1]]

        should_rewrite = (
            not locate_result.get("found")
            or bool(locate_result.get("needs_clarification"))
            or len(active_context) > 1
        )
        if should_rewrite:
            started = time.perf_counter()
            memory = backend.rewrite_memory(
                previous_memory=memory,
                locate_result=locate_result,
                frame_paths=active_context,
                reference_frame_paths=last_confirmed_frame_paths,
            )
            rewrite_duration = round(time.perf_counter() - started, 3)
            requests.append(
                BenchmarkRequest(
                    stage="rewrite",
                    batch_index=batch_index,
                    duration_seconds=rewrite_duration,
                    query_time_seconds=query_time,
                    frame_count=len(active_context),
                )
            )

    return BenchmarkRun(
        query_interval_seconds=int(query_plan["query_interval_seconds"]),
        recent_frame_count=int(query_plan["recent_frame_count"]),
        requests=requests,
    )


def summarize_benchmark_run(run: BenchmarkRun) -> Dict[str, Any]:
    init_durations = [req.duration_seconds for req in run.requests if req.stage == "init"]
    bootstrap_durations = [req.duration_seconds for req in run.requests if req.stage == "bootstrap"]
    locate_durations = [req.duration_seconds for req in run.requests if req.stage == "locate"]
    recovery_durations = [req.duration_seconds for req in run.requests if req.stage == "locate_recovery"]
    rewrite_durations = [req.duration_seconds for req in run.requests if req.stage == "rewrite"]

    cycles = []
    for locate in [req for req in run.requests if req.stage == "locate"]:
        locate_recovery = next(
            (
                req
                for req in run.requests
                if req.stage == "locate_recovery" and req.batch_index == locate.batch_index
            ),
            None,
        )
        rewrite = next(
            (
                req
                for req in run.requests
                if req.stage == "rewrite" and req.batch_index == locate.batch_index
            ),
            None,
        )
        total = locate.duration_seconds
        if locate_recovery is not None:
            total += locate_recovery.duration_seconds
        if rewrite is not None:
            total += rewrite.duration_seconds
        if total > 0:
            cycles.append(round(total, 3))

    locate_avg = round(sum(locate_durations) / len(locate_durations), 3) if locate_durations else 0.0
    recovery_avg = round(sum(recovery_durations) / len(recovery_durations), 3) if recovery_durations else 0.0
    rewrite_avg = round(sum(rewrite_durations) / len(rewrite_durations), 3) if rewrite_durations else 0.0
    cycle_avg = round(sum(cycles) / len(cycles), 3) if cycles else 0.0

    return {
        "query_interval_seconds": run.query_interval_seconds,
        "recent_frame_count": run.recent_frame_count,
        "request_count": len(run.requests),
        "init_duration_seconds": round(init_durations[0], 3) if init_durations else 0.0,
        "bootstrap_avg_seconds": round(sum(bootstrap_durations) / len(bootstrap_durations), 3)
        if bootstrap_durations
        else 0.0,
        "locate_avg_seconds": locate_avg,
        "locate_recovery_avg_seconds": recovery_avg,
        "rewrite_avg_seconds": rewrite_avg,
        "cycle_avg_seconds": cycle_avg,
        "backlog_ratio_vs_interval": round(
            cycle_avg / run.query_interval_seconds, 3
        )
        if run.query_interval_seconds
        else 0.0,
    }


def write_benchmark_result(
    output_path: Path,
    run: BenchmarkRun,
) -> Path:
    summary = summarize_benchmark_run(run)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "summary": summary,
                "requests": [asdict(request) for request in run.requests],
            },
            indent=2,
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    return output_path
