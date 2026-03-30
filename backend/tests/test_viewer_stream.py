from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image

from backend.agent.memory import AgentMemoryStore
from backend.persistence import ActiveSessionStore, LiveSessionStore
from skills.tracking.viewer_stream import build_tracking_viewer_payload


def _tiny_jpeg_base64() -> str:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color="white").save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_build_tracking_viewer_payload_includes_current_frame_memory_and_history(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    store = LiveSessionStore(state_root, frame_buffer_size=3)
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[{"track_id": 3, "bbox": [10, 20, 30, 40], "score": 0.95}],
        text="先看看画面",
        request_id="req_001",
        request_function="chat",
    )
    store.apply_agent_result(
        "sess_001",
        {
            "request_id": "req_001",
            "function": "tracking",
            "behavior": "reply",
            "frame_id": "frame_000001",
            "target_id": 3,
            "bbox": [10, 20, 30, 40],
            "text": "目标在左侧。",
            "memory": "黑色上衣，短发。",
        },
    )
    AgentMemoryStore(state_root, "sess_001").update_skill_cache(
        "tracking",
        {
            "latest_target_id": 3,
            "latest_memory": "黑色上衣，短发。",
            "pending_question": "",
        },
    )

    payload = build_tracking_viewer_payload(state_root=state_root, session_id="sess_001")

    assert payload["available"] is True
    assert payload["summary"]["target_id"] == 3
    assert payload["current_memory"] == "黑色上衣，短发。"
    assert payload["display_frame"]["frame_id"] == "frame_000001"
    assert payload["display_frame"]["target_id"] == 3
    assert payload["display_frame"]["image_data_url"].startswith("data:image/jpeg;base64,")
    assert payload["conversation_history"][-1]["text"] == "目标在左侧。"
    assert payload["memory_history"][-1]["memory"] == "黑色上衣，短发。"


def test_build_tracking_viewer_payload_handles_missing_session(tmp_path: Path) -> None:
    payload = build_tracking_viewer_payload(
        state_root=tmp_path / "state",
        session_id="missing_session",
    )

    assert payload["available"] is False
    assert payload["session_id"] == "missing_session"


def test_build_tracking_viewer_payload_uses_active_session_when_session_id_is_omitted(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    store = LiveSessionStore(state_root, frame_buffer_size=3)
    store.ingest_robot_event(
        session_id="sess_active",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[{"track_id": 5, "bbox": [10, 20, 30, 40], "score": 0.95}],
        text="观察画面",
    )
    ActiveSessionStore(state_root).write("sess_active")

    payload = build_tracking_viewer_payload(state_root=state_root)

    assert payload["available"] is True
    assert payload["session_id"] == "sess_active"


def test_build_tracking_viewer_payload_handles_missing_active_session(tmp_path: Path) -> None:
    payload = build_tracking_viewer_payload(
        state_root=tmp_path / "state",
    )

    assert payload["available"] is False
    assert payload["session_id"] is None
