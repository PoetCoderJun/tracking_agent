from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from capabilities.tracking.evaluation import benchmark as tracking_benchmark
from world.perception.stream import RobotDetection


def test_run_sequence_benchmark_uses_single_runtime_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sequence = tracking_benchmark.BenchmarkSequence(
        name="demo",
        video_path=tmp_path / "raw_video.mp4",
        labels_path=tmp_path / "labels.txt",
    )
    calls: list[str] = []
    expected = tracking_benchmark.SequenceBenchmarkResult(
        name="demo",
        evaluated_frames=1,
        predicted_frames=1,
        success_frames=1,
        success_rate=1.0,
        success_rate_percent=100.0,
        mean_center_distance_px=0.0,
        target_track_id=7,
        initial_match_iou=1.0,
        distance_threshold_px=50.0,
        frame_step=1,
        first_labeled_frame=0,
    )

    def fake_rebind(**kwargs: object) -> tracking_benchmark.SequenceBenchmarkResult:
        calls.append("rebind")
        assert kwargs["sequence"] == sequence
        return expected

    monkeypatch.setattr(tracking_benchmark, "run_sequence_benchmark_rebind_fsm", fake_rebind)

    result = tracking_benchmark.run_sequence_benchmark(
        sequence=sequence,
        model_path=tmp_path / "model.pt",
        tracker="tracker.yaml",
        device=None,
        conf=0.25,
        imgsz=None,
        person_class_id=0,
        distance_threshold_px=50.0,
        max_frames=1,
        env_file=tmp_path / ".ENV",
        device_id="robot_01",
        continue_text="继续跟踪",
        observation_interval_seconds=1.0,
        benchmark_run_root=tmp_path / "runs",
        tracker_fps=8.0,
    )

    assert calls == ["rebind"]
    assert result == expected
    assert not hasattr(tracking_benchmark, "run_sequence_benchmark_paper_stream")
    assert not hasattr(tracking_benchmark, "run_sequence_benchmark_project_perception")
    assert not hasattr(tracking_benchmark, "run_sequence_benchmark_stack_chain")


def test_run_sequence_benchmark_reuses_production_surfaces(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sequence_dir = tmp_path / "dataset" / "demo"
    sequence_dir.mkdir(parents=True)
    video_path = sequence_dir / "raw_video.mp4"
    video_path.write_bytes(b"")
    labels_path = sequence_dir / "labels.txt"
    labels_path.write_text("0 10 10 20 20\n", encoding="utf-8")

    sequence = tracking_benchmark.BenchmarkSequence(
        name="demo",
        video_path=video_path,
        labels_path=labels_path,
    )

    class FakePerceptionService:
        def __init__(self, *, state_root: Path) -> None:
            self.state_root = state_root

        def prepare(self, *, fresh_state: bool) -> None:
            assert fresh_state is True

        def write_observation(self, event: object) -> None:
            _ = event

    class FakeLoadedSession:
        def __init__(self, tracking_state: dict[str, object], latest_result: dict[str, object]) -> None:
            self.capabilities = {"tracking-init": tracking_state}
            self.latest_result = latest_result

    class FakeSessions:
        def __init__(self, *, state_root: Path) -> None:
            self.state_root = state_root
            self.tracking_state: dict[str, object] = {}
            self.latest_result: dict[str, object] = {}

        def load(self, session_id: str, device_id: str | None = None) -> FakeLoadedSession:
            _ = session_id
            _ = device_id
            return FakeLoadedSession(dict(self.tracking_state), dict(self.latest_result))

    calls: list[str] = []

    def fake_results(**kwargs: object):
        _ = kwargs
        yield (
            0,
            object(),
            SimpleNamespace(orig_img=object()),
        )

    def fake_save_frame_image(frame: object, destination: Path) -> None:
        _ = frame
        destination.write_bytes(b"frame")

    def fake_init(**kwargs: object) -> dict[str, object]:
        calls.append("init")
        assert "apply_tracking_payload" not in kwargs
        sessions = kwargs["sessions"]
        sessions.tracking_state = {"latest_target_id": 7}
        sessions.latest_result = {"decision": "bind", "found": True, "target_id": 7}
        return {"status": "processed"}

    def fake_due_tracking_step(**kwargs: object) -> dict[str, object]:
        calls.append("runner")
        sessions = kwargs["sessions"]
        sessions.latest_result = {"decision": "review", "found": True, "target_id": 7}
        return {"trigger": "cadence_review"}

    monkeypatch.setattr(tracking_benchmark, "LocalPerceptionService", FakePerceptionService)
    monkeypatch.setattr(tracking_benchmark, "AgentSessionStore", FakeSessions)
    monkeypatch.setattr(tracking_benchmark, "load_yolo", lambda: (lambda model_path: object()))
    monkeypatch.setattr(tracking_benchmark, "probe_video_fps", lambda path: 30.0)
    monkeypatch.setattr(tracking_benchmark, "_results_for_video_file_at_target_fps", fake_results)
    monkeypatch.setattr(tracking_benchmark, "extract_person_detections", lambda result, person_class_id: [RobotDetection(track_id=7, bbox=[10, 10, 30, 30], score=0.9)])
    monkeypatch.setattr(tracking_benchmark, "save_frame_image", fake_save_frame_image)
    monkeypatch.setattr(tracking_benchmark, "process_tracking_init_direct", fake_init)
    monkeypatch.setattr(tracking_benchmark, "run_due_tracking_step", fake_due_tracking_step)
    monkeypatch.setattr(tracking_benchmark, "tracking_state_snapshot", lambda state: dict(state))

    result = tracking_benchmark.run_sequence_benchmark_rebind_fsm(
        sequence=sequence,
        model_path=tmp_path / "model.pt",
        tracker="tracker.yaml",
        device=None,
        conf=0.25,
        imgsz=None,
        person_class_id=0,
        distance_threshold_px=50.0,
        max_frames=1,
        env_file=tmp_path / ".ENV",
        device_id="robot_01",
        continue_text="继续跟踪",
        benchmark_run_root=tmp_path / "runs",
        observation_interval_seconds=1.0,
        tracker_fps=8.0,
    )

    assert calls == ["init", "runner"]
    assert result.name == "demo"
    assert result.success_frames == 1
    assert result.predicted_frames == 1
    assert not hasattr(tracking_benchmark, "_apply_processed_tracking_payload_without_rewrite")
    assert not hasattr(tracking_benchmark, "_apply_processed_tracking_payload_with_sync_rewrite")


def test_benchmark_dataset_report_has_no_pipeline_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sequence_dir = tmp_path / "dataset" / "demo"
    sequence_dir.mkdir(parents=True)
    (sequence_dir / "raw_video.mp4").write_bytes(b"")
    (sequence_dir / "labels.txt").write_text("0 10 10 20 20\n", encoding="utf-8")

    expected = tracking_benchmark.SequenceBenchmarkResult(
        name="demo",
        evaluated_frames=1,
        predicted_frames=1,
        success_frames=1,
        success_rate=1.0,
        success_rate_percent=100.0,
        mean_center_distance_px=0.0,
        target_track_id=7,
        initial_match_iou=1.0,
        distance_threshold_px=50.0,
        frame_step=1,
        first_labeled_frame=0,
    )
    monkeypatch.setattr(tracking_benchmark, "run_sequence_benchmark", lambda **kwargs: expected)

    report = tracking_benchmark.benchmark_dataset(
        dataset_root=tmp_path / "dataset",
        requested_sequences=None,
        model_path=tmp_path / "model.pt",
        tracker="tracker.yaml",
        device=None,
        conf=0.25,
        imgsz=None,
        person_class_id=0,
        distance_threshold_px=50.0,
        max_frames=1,
        env_file=tmp_path / ".ENV",
        device_id="robot_01",
        continue_text="继续跟踪",
        observation_interval_seconds=1.0,
        benchmark_run_root=tmp_path / "runs",
        tracker_fps=8.0,
    )

    assert "pipeline" not in report
    assert "pipeline_note" not in report["protocol"]
    assert "runtime_alignment_note" in report["protocol"]
