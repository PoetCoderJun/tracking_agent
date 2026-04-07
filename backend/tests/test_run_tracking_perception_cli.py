from scripts.run_tracking_perception import (
    DEFAULT_CAMERA_SOURCE,
    DEFAULT_PERSON_MODEL,
    VIDEO_TRACK_FPS,
    _prepare_perception_session,
    _extract_person_detections,
    _normalize_xyxy_bbox,
    _should_emit_event,
    _should_emit_video_sample,
    _track_kwargs,
    _video_frame_step,
    parse_args,
)


def test_parse_args_defaults_interval_to_one_second(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_perception.py"],
    )
    args = parse_args()
    assert args.source == DEFAULT_CAMERA_SOURCE
    assert args.interval_seconds == 1.0
    assert args.observation_text == ""
    assert args.model == DEFAULT_PERSON_MODEL
    assert args.device is None
    assert args.tracker == "bytetrack.yaml"
    assert args.imgsz is None
    assert args.vid_stride == 1
    assert args.fresh_session is False
    assert args.state_root == "./.runtime/agent-runtime"
    assert args.observation_window_seconds == 5.0
    assert args.save_keyframe_every_seconds == 1.0
    assert args.keyframe_retention_seconds == 10.0


def test_parse_args_accepts_device_and_vid_stride(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_perception.py",
            "--source",
            "demo.mp4",
            "--device",
            "mps",
            "--vid-stride",
            "3",
        ],
    )
    args = parse_args()
    assert args.device == "mps"
    assert args.vid_stride == 3


def test_parse_args_accepts_window_and_keyframe_intervals(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_perception.py",
            "--observation-window-seconds",
            "7.5",
            "--save-keyframe-every-seconds",
            "3.0",
            "--keyframe-retention-seconds",
            "12.0",
        ],
    )
    args = parse_args()
    assert args.observation_window_seconds == 7.5
    assert args.save_keyframe_every_seconds == 3.0
    assert args.keyframe_retention_seconds == 12.0


def test_parse_args_accepts_local_runtime_paths(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_perception.py",
            "--source",
            "0",
            "--state-root",
            "./.runtime/custom-state",
            "--output-dir",
            "./.runtime/custom-perception",
            "--max-event-log-lines",
            "120",
        ],
    )
    args = parse_args()

    assert args.state_root == "./.runtime/custom-state"
    assert args.output_dir == "./.runtime/custom-perception"
    assert args.max_event_log_lines == 120

def test_normalize_xyxy_bbox_sorts_reversed_coordinates() -> None:
    assert _normalize_xyxy_bbox([384, 101, 305, 384]) == [305, 101, 384, 384]


def test_extract_person_detections_normalizes_reversed_bbox_coordinates() -> None:
    class FakeTensor:
        def __init__(self, values):
            self._values = values

        def int(self):
            return self

        def tolist(self):
            return self._values

    class FakeBoxes:
        xyxy = FakeTensor([[384, 101, 305, 384]])
        conf = FakeTensor([0.92])
        cls = FakeTensor([0])
        id = FakeTensor([7])

    class FakeResult:
        boxes = FakeBoxes()

    detections = _extract_person_detections(FakeResult(), person_class_id=0)
    assert detections[0].bbox == [305, 101, 384, 384]


def test_should_emit_event_respects_frame_and_time_gates() -> None:
    assert _should_emit_event(frame_index=3, sample_every=3, now_monotonic=6.0, next_emit_at=5.0)
    assert not _should_emit_event(frame_index=2, sample_every=3, now_monotonic=6.0, next_emit_at=5.0)
    assert not _should_emit_event(frame_index=3, sample_every=3, now_monotonic=4.9, next_emit_at=5.0)


def test_should_emit_video_sample_uses_video_timeline_only() -> None:
    assert _should_emit_video_sample(
        frame_index=91,
        sample_every=1,
        fps=30.0,
        next_video_emit_at=3.0,
    )
    assert not _should_emit_video_sample(
        frame_index=90,
        sample_every=1,
        fps=30.0,
        next_video_emit_at=3.0,
    )


def test_video_frame_step_samples_one_frame_per_interval() -> None:
    assert VIDEO_TRACK_FPS == 8.0
    assert _video_frame_step(fps=30.0, vid_stride=1) == 4
    assert _video_frame_step(fps=30.0, vid_stride=2) == 8


def test_track_kwargs_omits_imgsz_when_not_set(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_tracking_perception.py", "--source", "demo.mp4", "--tracker", "botsort.yaml"],
    )
    args = parse_args()

    kwargs = _track_kwargs(source="demo.mp4", args=args, stream=True, persist=True)

    assert "imgsz" not in kwargs
    assert kwargs["tracker"] == "botsort.yaml"

def test_prepare_perception_session_reuses_existing_session_without_reset(tmp_path) -> None:
    from agent.session_store import AgentSessionStore
    from backend.perception import LocalPerceptionService

    state_root = tmp_path / "state"
    runtime = AgentSessionStore(state_root=state_root)
    perception = LocalPerceptionService(state_root=state_root)
    runtime.start_fresh_session("sess_001", device_id="robot_01")
    runtime.patch_skill_state("sess_001", skill_name="tracking", patch={"latest_target_id": 7})

    _prepare_perception_session(
        perception_service=perception,
        session_id="sess_001",
        device_id="robot_01",
        fresh_session=False,
    )

    context = runtime.load("sess_001")
    assert context.skill_cache["tracking"]["latest_target_id"] == 7


def test_prepare_perception_session_resets_existing_session_when_requested(tmp_path) -> None:
    from agent.session_store import AgentSessionStore
    from backend.perception import LocalPerceptionService

    state_root = tmp_path / "state"
    runtime = AgentSessionStore(state_root=state_root)
    perception = LocalPerceptionService(state_root=state_root)
    runtime.start_fresh_session("sess_001", device_id="robot_01")
    runtime.patch_skill_state("sess_001", skill_name="tracking", patch={"latest_target_id": 7})

    _prepare_perception_session(
        perception_service=perception,
        session_id="sess_001",
        device_id="robot_01",
        fresh_session=True,
    )

    context = runtime.load("sess_001")
    assert context.skill_cache == {}
