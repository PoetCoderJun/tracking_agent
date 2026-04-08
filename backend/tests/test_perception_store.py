from __future__ import annotations

from pathlib import Path

from PIL import Image

from backend.runtime_session import AgentSessionStore
from backend.tracking.context import build_tracking_context
from backend.perception import (
    CAMERA_SENSOR_NAME,
    PERSON_DETECTION_KIND,
    DerivedObservation,
    LocalPerceptionService,
    Observation,
    PerceptionRecorder,
    PerceptionStore,
    RobotDetection,
    RobotFrame,
    RobotIngestEvent,
)


def _frame_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), color="white").save(path, format="JPEG")
    return path


def test_perception_store_keeps_recent_time_window_only() -> None:
    store = PerceptionStore(default_window_seconds=2.0)
    store.append_observation(
        Observation(id="obs_001", ts_ms=1000, sensor=CAMERA_SENSOR_NAME, kind="image", payload={})
    )
    store.append_observation(
        Observation(id="obs_002", ts_ms=2500, sensor=CAMERA_SENSOR_NAME, kind="image", payload={})
    )
    store.append_observation(
        Observation(id="obs_003", ts_ms=4100, sensor=CAMERA_SENSOR_NAME, kind="image", payload={})
    )

    assert [item.id for item in store.window(CAMERA_SENSOR_NAME)] == ["obs_002", "obs_003"]
    assert [item.id for item in store.window(CAMERA_SENSOR_NAME, seconds=1.0)] == ["obs_003"]


def test_perception_store_tracks_latest_derived_by_kind_and_sensor() -> None:
    store = PerceptionStore(default_window_seconds=5.0)
    store.append_derived(
        DerivedObservation(
            id="drv_001",
            source_id="obs_001",
            ts_ms=1000,
            kind=PERSON_DETECTION_KIND,
            sensor=CAMERA_SENSOR_NAME,
            payload={"detections": [{"track_id": 1}]},
        )
    )
    latest = store.latest_derived(PERSON_DETECTION_KIND, sensor=CAMERA_SENSOR_NAME)
    assert latest is not None
    assert latest.payload["detections"][0]["track_id"] == 1


def test_perception_recorder_saves_keyframes_at_low_frequency(tmp_path: Path) -> None:
    source_a = _frame_image(tmp_path / "source_a.jpg")
    source_b = _frame_image(tmp_path / "source_b.jpg")
    recorder = PerceptionRecorder(tmp_path / "keyframes", save_frame_every_seconds=2.0)

    saved_a = recorder.save_frame_reference(
        sensor=CAMERA_SENSOR_NAME,
        frame_id="frame_000001",
        ts_ms=1000,
        source_path=source_a,
    )
    saved_b = recorder.save_frame_reference(
        sensor=CAMERA_SENSOR_NAME,
        frame_id="frame_000002",
        ts_ms=2000,
        source_path=source_b,
    )
    saved_c = recorder.save_frame_reference(
        sensor=CAMERA_SENSOR_NAME,
        frame_id="frame_000003",
        ts_ms=3100,
        source_path=source_b,
    )

    assert saved_a is not None and saved_a.exists()
    assert saved_b is None
    assert saved_c is not None and saved_c.exists()


def test_perception_recorder_prunes_history_to_retention_window(tmp_path: Path) -> None:
    source = _frame_image(tmp_path / "source.jpg")
    recorder = PerceptionRecorder(
        tmp_path / "keyframes",
        save_frame_every_seconds=1.0,
        retention_seconds=2.0,
    )

    recorder.save_frame_reference(sensor=CAMERA_SENSOR_NAME, frame_id="frame_000001", ts_ms=1000, source_path=source)
    recorder.save_frame_reference(sensor=CAMERA_SENSOR_NAME, frame_id="frame_000002", ts_ms=2000, source_path=source)
    recorder.save_frame_reference(sensor=CAMERA_SENSOR_NAME, frame_id="frame_000003", ts_ms=3000, source_path=source)

    saved_paths = recorder.saved_frame_paths(sensor=CAMERA_SENSOR_NAME)
    assert [path.stem for path in saved_paths] == ["frame_000002", "frame_000003"]


def test_perception_recorder_prunes_existing_history_after_restart(tmp_path: Path) -> None:
    source = _frame_image(tmp_path / "source.jpg")
    root = tmp_path / "keyframes"

    recorder = PerceptionRecorder(
        root,
        save_frame_every_seconds=1.0,
        retention_seconds=2.0,
    )
    recorder.save_frame_reference(sensor=CAMERA_SENSOR_NAME, frame_id="frame_000001", ts_ms=1000, source_path=source)
    recorder.save_frame_reference(sensor=CAMERA_SENSOR_NAME, frame_id="frame_000002", ts_ms=2000, source_path=source)

    restarted = PerceptionRecorder(
        root,
        save_frame_every_seconds=1.0,
        retention_seconds=2.0,
    )
    restarted.save_frame_reference(sensor=CAMERA_SENSOR_NAME, frame_id="frame_000003", ts_ms=3000, source_path=source)

    saved_paths = restarted.saved_frame_paths(sensor=CAMERA_SENSOR_NAME)
    assert [path.stem for path in saved_paths] == ["frame_000002", "frame_000003"]


def test_local_perception_service_exposes_recent_camera_queries(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    service = LocalPerceptionService(state_root=state_root, observation_window_seconds=5.0)
    frame_a = _frame_image(tmp_path / "frame_a.jpg")
    frame_b = _frame_image(tmp_path / "frame_b.jpg")

    service.write_observation(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(frame_id="frame_000001", timestamp_ms=1000, image_path=str(frame_a)),
            detections=[RobotDetection(track_id=1, bbox=[1, 2, 3, 4], score=0.9)],
            text="",
        ),
    )
    service.write_observation(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(frame_id="frame_000002", timestamp_ms=2500, image_path=str(frame_b)),
            detections=[RobotDetection(track_id=2, bbox=[5, 6, 7, 8], score=0.8)],
            text="",
        ),
    )

    latest = service.latest_camera_observation()
    recent = service.recent_camera_observations(seconds=1.0)
    detections = service.latest_person_detection()

    assert latest is not None
    assert latest["id"] == "frame_000002"
    assert [item["id"] for item in recent] == ["frame_000002"]
    assert detections is not None
    assert detections["payload"]["detections"][0]["track_id"] == 2


def test_local_perception_service_describes_saved_state(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    service = LocalPerceptionService(state_root=state_root, observation_window_seconds=5.0)
    frame_path = _frame_image(tmp_path / "frame.jpg")

    service.write_observation(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(frame_id="frame_000001", timestamp_ms=1000, image_path=str(frame_path)),
            detections=[RobotDetection(track_id=9, bbox=[1, 2, 3, 4], score=0.9)],
            text="继续跟踪",
        ),
        request_id="req_001",
        request_function="chat",
    )

    description = service.describe_saved_state()

    assert description["persisted"]["recent_camera_observation_count"] == 1
    assert description["persisted"]["latest_camera_observation"]["id"] == "frame_000001"
    assert description["persisted"]["saved_keyframe_count"] == 1


def test_local_perception_service_reset_clears_snapshot_and_saved_keyframes(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    service = LocalPerceptionService(state_root=state_root, observation_window_seconds=5.0)
    frame_path = _frame_image(tmp_path / "frame.jpg")

    service.write_observation(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(frame_id="frame_000001", timestamp_ms=1000, image_path=str(frame_path)),
            detections=[RobotDetection(track_id=9, bbox=[1, 2, 3, 4], score=0.9)],
            text="继续跟踪",
        ),
    )

    reset_snapshot = service.reset()

    assert reset_snapshot["latest_camera_observation"] is None
    assert reset_snapshot["saved_keyframes"] == []
    assert service.save_frame_reference(
        frame_id="frame_000002",
        ts_ms=2000,
        source_path=frame_path,
        force=True,
    ) is not None

    service.reset()
    assert service.describe_saved_state()["persisted"]["saved_keyframe_count"] == 0


def test_tracking_context_helpers_match_existing_payload_shape(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    runtime = AgentSessionStore(state_root)
    perception = LocalPerceptionService(state_root)
    frame_path = _frame_image(tmp_path / "frame.jpg")
    runtime.patch_skill_state(
        "sess_001",
        skill_name="tracking",
        patch={"latest_target_id": 7, "target_description": "黑衣服的人"},
    )
    perception.write_observation(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(frame_id="frame_000001", timestamp_ms=1710000000000, image_path=str(frame_path)),
            detections=[RobotDetection(track_id=7, bbox=[10, 20, 30, 40], score=0.95)],
            text="继续跟踪",
        ),
        request_id="req_001",
        request_function="chat",
    )
    context = runtime.load("sess_001")

    tracking_context = build_tracking_context(
        context,
        request_id="req_001",
    )

    assert tracking_context["latest_target_id"] == 7
    assert tracking_context["frames"][0]["detections"][0]["track_id"] == 7


def test_tracking_context_helpers_prefer_perception_store_over_session_frames(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    runtime = AgentSessionStore(state_root)
    perception = LocalPerceptionService(state_root)
    frame_path = _frame_image(tmp_path / "frame.jpg")

    perception.write_observation(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(frame_id="frame_000009", timestamp_ms=1710000000000, image_path=str(frame_path)),
            detections=[RobotDetection(track_id=42, bbox=[10, 20, 30, 40], score=0.95)],
            text="继续跟踪",
        ),
        request_id="req_009",
        request_function="chat",
    )
    context = runtime.load("sess_001")
    context.session["recent_frames"] = []

    tracking_context = build_tracking_context(
        context,
        request_id="req_009",
    )

    assert tracking_context["frames"][0]["frame_id"] == "frame_000009"
    assert tracking_context["frames"][0]["detections"][0]["track_id"] == 42


def test_tracking_context_filters_excluded_track_ids(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    runtime = AgentSessionStore(state_root)
    perception = LocalPerceptionService(state_root)
    frame_path = _frame_image(tmp_path / "frame.jpg")

    perception.write_observation(
        RobotIngestEvent(
            session_id="sess_001",
            device_id="robot_01",
            frame=RobotFrame(frame_id="frame_000011", timestamp_ms=1710000000000, image_path=str(frame_path)),
            detections=[
                RobotDetection(track_id=7, bbox=[10, 20, 30, 40], score=0.95),
                RobotDetection(track_id=12, bbox=[30, 20, 50, 40], score=0.92),
                RobotDetection(track_id=21, bbox=[50, 20, 70, 40], score=0.90),
            ],
            text="继续跟踪",
        ),
        request_id="req_011",
        request_function="chat",
    )
    context = runtime.load("sess_001")

    tracking_context = build_tracking_context(
        context,
        request_id="req_011",
        excluded_track_ids=[12],
    )

    assert tracking_context["excluded_track_ids"] == [12]
    assert [detection["track_id"] for detection in tracking_context["frames"][0]["detections"]] == [7, 21]
