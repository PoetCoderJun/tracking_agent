from __future__ import annotations

from tracking_agent.benchmark_tracking import (
    BenchmarkRequest,
    BenchmarkRun,
    summarize_benchmark_run,
)


def test_summarize_benchmark_run_computes_cycle_totals_and_backlog_ratio() -> None:
    run = BenchmarkRun(
        query_interval_seconds=5,
        recent_frame_count=4,
        requests=[
            BenchmarkRequest(stage="init", batch_index=0, duration_seconds=2.0),
            BenchmarkRequest(stage="locate", batch_index=1, duration_seconds=6.5),
            BenchmarkRequest(stage="rewrite", batch_index=1, duration_seconds=4.0),
            BenchmarkRequest(stage="locate", batch_index=2, duration_seconds=5.5),
            BenchmarkRequest(stage="rewrite", batch_index=2, duration_seconds=3.0),
        ],
    )

    summary = summarize_benchmark_run(run)

    assert summary["query_interval_seconds"] == 5
    assert summary["recent_frame_count"] == 4
    assert summary["init_duration_seconds"] == 2.0
    assert summary["locate_avg_seconds"] == 6.0
    assert summary["rewrite_avg_seconds"] == 3.5
    assert summary["cycle_avg_seconds"] == 9.5
    assert summary["backlog_ratio_vs_interval"] == 1.9
