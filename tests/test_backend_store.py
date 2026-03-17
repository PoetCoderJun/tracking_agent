from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image

from tracking_agent.backend_store import BackendStore


def _tiny_jpeg_base64() -> str:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color="white").save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_ingest_robot_event_saves_frame_without_interpreting_target_description(tmp_path: Path) -> None:
    store = BackendStore(tmp_path / "state", frame_buffer_size=2)

    session = store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 12, "bbox": [10, 20, 30, 40], "score": 0.95},
        ],
        text="跟踪穿黑衣服的人",
    )

    assert session.target_description == ""
    assert len(session.recent_frames) == 1
    assert Path(session.recent_frames[0].image_path).exists()
    assert session.conversation_history[0]["role"] == "user"
    assert session.conversation_history[0]["text"] == "跟踪穿黑衣服的人"


def test_ingest_robot_event_truncates_recent_frames_buffer(tmp_path: Path) -> None:
    store = BackendStore(tmp_path / "state", frame_buffer_size=2)

    for index in range(3):
        store.ingest_robot_event(
            session_id="sess_001",
            device_id="robot_01",
            frame={
                "frame_id": f"frame_{index:06d}",
                "timestamp_ms": 1710000000000 + index,
                "image_base64": _tiny_jpeg_base64(),
            },
            detections=[],
            text="",
        )

    session = store.load_session("sess_001")
    assert [frame.frame_id for frame in session.recent_frames] == [
        "frame_000001",
        "frame_000002",
    ]


def test_apply_agent_result_backfills_bbox_from_latest_frame(tmp_path: Path) -> None:
    store = BackendStore(tmp_path / "state", frame_buffer_size=3)
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 15, "bbox": [100, 120, 180, 260], "score": 0.94},
            {"track_id": 27, "bbox": [200, 140, 280, 300], "score": 0.88},
        ],
        text="",
    )

    session = store.apply_agent_result(
        "sess_001",
        {
            "text": "我认为当前目标是 ID 15。",
            "target_id": 15,
            "found": True,
            "needs_clarification": False,
            "clarification_question": None,
            "memory": "短发，黑衣服。",
        },
    )

    assert session.latest_target_id == 15
    assert session.latest_memory == "短发，黑衣服。"
    assert session.latest_result is not None
    assert session.latest_result["target_id"] == 15
    assert "bounding_box_id" not in session.latest_result
    assert session.latest_result["bbox"] == [100, 120, 180, 260]
    assert len(session.result_history) == 1
    assert session.result_history[0]["memory"] == "短发，黑衣服。"
    assert session.latest_confirmed_frame_path is not None


def test_apply_agent_result_uses_supplied_frame_id_instead_of_newer_latest_frame(tmp_path: Path) -> None:
    store = BackendStore(tmp_path / "state", frame_buffer_size=3)
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 15, "bbox": [100, 120, 180, 260], "score": 0.94},
            {"track_id": 27, "bbox": [200, 140, 280, 300], "score": 0.88},
        ],
        text="",
    )
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000002",
            "timestamp_ms": 1710000003000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 15, "bbox": [102, 122, 182, 262], "score": 0.95},
            {"track_id": 31, "bbox": [220, 150, 300, 310], "score": 0.84},
        ],
        text="持续跟踪",
    )

    session = store.apply_agent_result(
        "sess_001",
        {
            "frame_id": "frame_000001",
            "text": "我认为 frame_000001 的目标是 ID 15。",
            "target_id": 15,
            "found": True,
            "needs_clarification": False,
            "clarification_question": None,
            "memory": "短发，黑衣服。",
        },
    )

    assert session.latest_result is not None
    assert session.latest_result["frame_id"] == "frame_000001"
    assert session.latest_result["bbox"] == [100, 120, 180, 260]


def test_session_payload_stays_raw_backend_state(tmp_path: Path) -> None:
    store = BackendStore(tmp_path / "state", frame_buffer_size=3)
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 15, "bbox": [100, 120, 180, 260], "score": 0.94},
            {"track_id": 27, "bbox": [200, 140, 280, 300], "score": 0.88},
        ],
        text="",
    )
    store.apply_agent_result(
        "sess_001",
        {
            "text": "我认为当前目标是 15。",
            "bounding_box_id": 15,
            "found": True,
            "needs_clarification": False,
            "clarification_question": None,
            "memory": "短发，黑衣服。",
        },
    )

    payload = store.session_payload("sess_001")

    assert "latest_bounding_box_id" not in payload
    assert payload["latest_result"]["target_id"] == 15
    assert "bounding_box_id" not in payload["latest_result"]
    assert payload["recent_frames"][-1]["detections"][0]["track_id"] == 15
    assert "bounding_box_id" not in payload["recent_frames"][-1]["detections"][0]


def test_apply_agent_result_hides_bbox_when_target_not_found(tmp_path: Path) -> None:
    store = BackendStore(tmp_path / "state", frame_buffer_size=3)
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 15, "bbox": [100, 120, 180, 260], "score": 0.94},
            {"track_id": 27, "bbox": [200, 140, 280, 300], "score": 0.88},
        ],
        text="",
    )
    confirmed = store.apply_agent_result(
        "sess_001",
        {
            "text": "我认为当前目标是 ID 15。",
            "target_id": 15,
            "found": True,
            "needs_clarification": False,
            "clarification_question": None,
            "memory": "短发，黑衣服。",
        },
    )

    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000002",
            "timestamp_ms": 1710000003000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 15, "bbox": [102, 122, 182, 262], "score": 0.95},
            {"track_id": 31, "bbox": [220, 150, 300, 310], "score": 0.84},
        ],
        text="持续跟踪",
    )
    missing = store.apply_agent_result(
        "sess_001",
        {
            "text": "当前帧没有可靠找到目标。",
            "target_id": 15,
            "found": False,
            "needs_clarification": False,
            "clarification_question": None,
            "memory": "短发，黑衣服。",
        },
    )

    assert confirmed.latest_target_id == 15
    assert missing.latest_target_id == 15
    assert missing.latest_result is not None
    assert missing.latest_result["found"] is False
    assert missing.latest_result["bbox"] is None
    assert missing.latest_confirmed_frame_path == confirmed.latest_confirmed_frame_path
    assert [detection.track_id for detection in missing.latest_confirmed_detections] == [15, 27]


def test_apply_memory_update_rewrites_latest_memory_for_matching_result(tmp_path: Path) -> None:
    store = BackendStore(tmp_path / "state", frame_buffer_size=3)
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 15, "bbox": [100, 120, 180, 260], "score": 0.94},
        ],
        text="",
    )
    store.apply_agent_result(
        "sess_001",
        {
            "text": "我认为当前目标是 ID 15。",
            "target_id": 15,
            "found": True,
            "needs_clarification": False,
            "clarification_question": None,
            "memory": "",
        },
    )

    updated = store.apply_memory_update(
        "sess_001",
        memory="短发，黑衣服，优先看鞋子。",
        expected_frame_id="frame_000001",
        expected_target_id=15,
        expected_target_crop=None,
    )

    assert updated.latest_memory == "短发，黑衣服，优先看鞋子。"
    assert updated.latest_result is not None
    assert updated.latest_result["memory"] == "短发，黑衣服，优先看鞋子。"
    assert updated.result_history[-1]["memory"] == "短发，黑衣服，优先看鞋子。"


def test_apply_memory_update_skips_stale_background_result(tmp_path: Path) -> None:
    store = BackendStore(tmp_path / "state", frame_buffer_size=3)
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 15, "bbox": [100, 120, 180, 260], "score": 0.94},
        ],
        text="",
    )
    store.apply_agent_result(
        "sess_001",
        {
            "text": "第一轮确认目标。",
            "target_id": 15,
            "found": True,
            "needs_clarification": False,
            "clarification_question": None,
            "memory": "第一轮 memory",
        },
    )
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000002",
            "timestamp_ms": 1710000003000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 15, "bbox": [102, 122, 182, 262], "score": 0.95},
        ],
        text="持续跟踪",
    )
    latest = store.apply_agent_result(
        "sess_001",
        {
            "text": "第二轮继续跟踪。",
            "target_id": 15,
            "found": True,
            "needs_clarification": False,
            "clarification_question": None,
            "memory": "第二轮 memory",
        },
    )

    stale = store.apply_memory_update(
        "sess_001",
        memory="过时的后台 memory",
        expected_frame_id="frame_000001",
        expected_target_id=15,
        expected_target_crop=None,
    )

    assert stale.latest_memory == latest.latest_memory
    assert stale.latest_result == latest.latest_result


def test_apply_agent_result_init_clears_previous_target_context(tmp_path: Path) -> None:
    store = BackendStore(tmp_path / "state", frame_buffer_size=3)
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 15, "bbox": [100, 120, 180, 260], "score": 0.94},
        ],
        text="跟踪穿黑衣服的人",
    )
    store.apply_agent_result(
        "sess_001",
        {
            "behavior": "track",
            "text": "继续跟踪原目标。",
            "target_id": 15,
            "found": True,
            "needs_clarification": False,
            "clarification_question": None,
            "memory": "黑衣短发，优先看鞋子。",
            "target_description": "跟踪穿黑衣服的人",
            "latest_target_crop": "/tmp/original-crop.jpg",
        },
    )

    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000002",
            "timestamp_ms": 1710000003000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 31, "bbox": [210, 130, 290, 310], "score": 0.92},
        ],
        text="跟踪穿红衣服的人",
    )
    updated = store.apply_agent_result(
        "sess_001",
        {
            "behavior": "init",
            "frame_id": "frame_000002",
            "text": "请确认是不是右边穿红衣服的人。",
            "found": False,
            "needs_clarification": True,
            "clarification_question": "请确认是不是右边穿红衣服的人。",
            "target_description": "跟踪穿红衣服的人",
            "memory": "",
        },
    )

    assert updated.target_description == "跟踪穿红衣服的人"
    assert updated.latest_memory == ""
    assert updated.latest_target_id is None
    assert updated.latest_target_crop is None
    assert updated.latest_confirmed_frame_path is None
    assert updated.latest_confirmed_detections == []
    assert updated.pending_question == "请确认是不是右边穿红衣服的人。"


def test_reset_tracking_context_clears_memory_and_target_binding(tmp_path: Path) -> None:
    store = BackendStore(tmp_path / "state", frame_buffer_size=3)
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[
            {"track_id": 15, "bbox": [100, 120, 180, 260], "score": 0.94},
        ],
        text="跟踪穿黑衣服的人",
    )
    store.apply_agent_result(
        "sess_001",
        {
            "behavior": "track",
            "frame_id": "frame_000001",
            "text": "继续跟踪原目标。",
            "target_id": 15,
            "found": True,
            "needs_clarification": False,
            "clarification_question": None,
            "memory": "黑衣短发，优先看鞋子。",
            "target_description": "跟踪穿黑衣服的人",
            "latest_target_crop": "/tmp/original-crop.jpg",
        },
    )

    updated = store.reset_tracking_context("sess_001")

    assert updated.target_description == ""
    assert updated.latest_memory == ""
    assert updated.latest_target_id is None
    assert updated.latest_target_crop is None
    assert updated.latest_confirmed_frame_path is None
    assert updated.latest_confirmed_detections == []
    assert updated.pending_question is None
    assert updated.clarification_notes == []
    assert updated.result_history == []
    assert updated.latest_result is not None
    assert updated.latest_result["behavior"] == "reset"
    assert updated.latest_result["frame_id"] == "frame_000001"
