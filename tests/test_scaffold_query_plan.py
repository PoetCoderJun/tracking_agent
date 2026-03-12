from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tracking_agent.pipeline import build_query_batches, extract_video_to_frame_queue


ROOT = Path(__file__).resolve().parents[1]
TEST_VIDEO = ROOT / "test_data" / "0045.mp4"


@pytest.fixture(scope="session")
def extracted_manifest(tmp_path_factory: pytest.TempPathFactory):
    runtime_dir = tmp_path_factory.mktemp("runtime")
    manifest = extract_video_to_frame_queue(
        video_path=TEST_VIDEO,
        runtime_dir=runtime_dir,
        sample_fps=1.0,
    )
    return manifest, runtime_dir


def test_extract_video_to_frame_queue_writes_manifest(extracted_manifest) -> None:
    manifest, runtime_dir = extracted_manifest

    assert manifest.sample_fps == pytest.approx(1.0)
    assert len(manifest.frames) >= 80
    assert manifest.frames[0].timestamp_seconds == pytest.approx(0.0)
    assert manifest.frames[-1].timestamp_seconds == pytest.approx(len(manifest.frames) - 1)
    assert Path(manifest.current_frame).name == "current.jpg"
    assert Path(manifest.current_frame).exists()
    assert (runtime_dir / "frames" / "manifest.json").exists()


def test_build_query_batches_uses_recent_frames_window(extracted_manifest) -> None:
    manifest, _ = extracted_manifest

    batches = build_query_batches(
        frames=manifest.frames,
        query_interval_seconds=5,
        recent_frame_count=4,
    )

    assert len(batches) == int(manifest.frames[-1].timestamp_seconds) // 5 + 1
    assert batches[0].query_time_seconds == pytest.approx(0.0)
    assert [frame.timestamp_seconds for frame in batches[0].frames] == [0.0]
    assert batches[1].query_time_seconds == pytest.approx(5.0)
    assert batches[2].query_time_seconds == pytest.approx(10.0)
    assert [frame.timestamp_seconds for frame in batches[1].frames] == [2.0, 3.0, 4.0, 5.0]
    assert [frame.timestamp_seconds for frame in batches[2].frames] == [7.0, 8.0, 9.0, 10.0]


def test_cli_generates_frame_manifest_and_query_plan(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"

    result = subprocess.run(
        [
            sys.executable,
            "scaffold/cli/build_query_plan.py",
            "--video",
            str(TEST_VIDEO),
            "--runtime-dir",
            str(runtime_dir),
            "--sample-fps",
            "1",
            "--query-interval-seconds",
            "5",
            "--recent-frame-count",
            "4",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert "query_plan.json" in result.stdout

    query_plan_path = runtime_dir / "queries" / "query_plan.json"
    assert query_plan_path.exists()

    query_plan = json.loads(query_plan_path.read_text(encoding="utf-8"))
    assert query_plan["query_interval_seconds"] == 5
    assert query_plan["recent_frame_count"] == 4
    assert len(query_plan["batches"]) == 18
    assert query_plan["batches"][0]["query_time_seconds"] == 0.0
    assert len(query_plan["batches"][0]["frames"]) == 1
