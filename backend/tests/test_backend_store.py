from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from backend.persistence import LiveSessionStore


def _tiny_jpeg_base64() -> str:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), color="white").save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_ingest_robot_event_saves_generic_session_state(tmp_path: Path) -> None:
    store = LiveSessionStore(tmp_path / "state")

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
        text="look around",
        request_id="req_001",
        request_function="event",
    )

    assert session.latest_request_id == "req_001"
    assert session.latest_request_function == "event"
    assert session.latest_result is None
    assert session.conversation_history[0]["role"] == "user"
    assert session.conversation_history[0]["text"] == "look around"


def test_ingest_robot_event_does_not_persist_recent_frames_or_frame_files(tmp_path: Path) -> None:
    store = LiveSessionStore(tmp_path / "state")

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
    payload = json.loads((tmp_path / "state" / "sessions" / "sess_001" / "session.json").read_text(encoding="utf-8"))
    assert "recent_frames" not in payload
    assert not (tmp_path / "state" / "sessions" / "sess_001" / "frames").exists()


def test_apply_agent_result_preserves_generic_payload_shape(tmp_path: Path) -> None:
    store = LiveSessionStore(tmp_path / "state")
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
        text="inspect the scene",
        request_id="req_001",
        request_function="inspect",
    )

    session = store.apply_agent_result(
        "sess_001",
        {
            "request_id": "req_001",
            "function": "inspect",
            "behavior": "reply",
            "frame_id": "frame_000001",
            "text": "scene looks clear",
            "summary": {"objects": 1},
            "robot_response": {"action": "speak", "text": "scene looks clear"},
            "skill_state": {"should_not": "live_in_session"},
            "latest_result": {"should_not": "nest"},
            "raw_session": {"should_not": "persist"},
        },
    )

    assert session.latest_result is not None
    assert session.latest_result["request_id"] == "req_001"
    assert session.latest_result["function"] == "inspect"
    assert session.latest_result["frame_id"] == "frame_000001"
    assert session.latest_result["behavior"] == "reply"
    assert session.latest_result["text"] == "scene looks clear"
    assert session.latest_result["summary"] == {"objects": 1}
    assert session.latest_result["robot_response"]["action"] == "speak"
    assert "skill_state" not in session.latest_result
    assert "latest_result" not in session.latest_result
    assert "raw_session" not in session.latest_result
    assert session.result_history[-1]["summary"] == {"objects": 1}


def test_session_payload_stays_generic(tmp_path: Path) -> None:
    store = LiveSessionStore(tmp_path / "state")
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
            "text": "inspected current scene",
            "function": "inspect",
            "behavior": "reply",
            "memory": "generic note",
        },
    )

    payload = store.session_payload("sess_001")

    assert "user_preferences" not in payload
    assert "environment_map" not in payload
    assert "runner_state" not in payload
    assert "skill_cache" not in payload
    assert "target_description" not in payload
    assert "latest_target_id" not in payload
    assert "latest_memory" not in payload
    assert payload["latest_result"]["function"] == "inspect"
    assert "memory" not in payload["latest_result"]
    assert "recent_frames" not in payload
    assert payload["state"] == {
        "user_preferences": {},
        "environment": {},
        "runner": {},
        "capabilities": {},
    }


def test_conversation_history_keeps_full_chat_log(tmp_path: Path) -> None:
    store = LiveSessionStore(tmp_path / "state")
    store.ingest_robot_event(
        session_id="sess_chat",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[],
        text="初始化观察",
    )

    for index in range(25):
        request_id = f"req_{index:03d}"
        store.append_chat_request(
            session_id="sess_chat",
            device_id="robot_01",
            text=f"user turn {index}",
            request_id=request_id,
        )
        store.apply_agent_result(
            "sess_chat",
            {
                "request_id": request_id,
                "function": "chat",
                "behavior": "reply",
                "frame_id": "frame_000001",
                "text": f"assistant turn {index}",
            },
        )

    session = store.load_session("sess_chat")

    assert len(session.conversation_history) == 8
    assert session.conversation_history[0]["text"] == "user turn 21"
    assert session.conversation_history[-1]["text"] == "assistant turn 24"


def test_patch_latest_result_updates_current_result_and_history(tmp_path: Path) -> None:
    store = LiveSessionStore(tmp_path / "state")
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[],
        text="inspect",
        request_id="req_001",
        request_function="inspect",
    )
    store.apply_agent_result(
        "sess_001",
        {
            "request_id": "req_001",
            "function": "inspect",
            "behavior": "reply",
            "frame_id": "frame_000001",
            "text": "initial result",
            "memory": "",
        },
    )

    updated = store.patch_latest_result(
        "sess_001",
        {"memory": "updated memory", "text": "updated result"},
        expected_request_id="req_001",
        expected_frame_id="frame_000001",
    )

    assert updated.latest_result is not None
    assert "memory" not in updated.latest_result
    assert updated.latest_result["text"] == "updated result"
    assert "memory" not in updated.result_history[-1]
    assert updated.result_history[-1]["text"] == "updated result"


def test_reset_session_context_clears_result_history_but_keeps_frames_and_dialogue(
    tmp_path: Path,
) -> None:
    store = LiveSessionStore(tmp_path / "state")
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[],
        text="inspect the scene",
        request_id="req_001",
        request_function="inspect",
    )
    store.apply_agent_result(
        "sess_001",
        {
            "request_id": "req_001",
            "function": "inspect",
            "behavior": "reply",
            "frame_id": "frame_000001",
            "text": "scene is clear",
        },
    )

    updated = store.reset_session_context("sess_001")

    assert updated.latest_result is None
    assert updated.result_history == []
    assert "recent_frames" not in store.session_payload("sess_001")
    assert updated.conversation_history[0]["text"] == "inspect the scene"


def test_start_fresh_session_replaces_old_session_state_and_cleans_frames(tmp_path: Path) -> None:
    store = LiveSessionStore(tmp_path / "state")
    store.ingest_robot_event(
        session_id="sess_001",
        device_id="robot_01",
        frame={
            "frame_id": "frame_000001",
            "timestamp_ms": 1710000000000,
            "image_base64": _tiny_jpeg_base64(),
        },
        detections=[],
        text="stale context",
        request_id="req_001",
        request_function="inspect",
    )
    store.apply_agent_result(
        "sess_001",
        {
            "request_id": "req_001",
            "function": "inspect",
            "behavior": "reply",
            "frame_id": "frame_000001",
            "text": "stale result",
        },
    )

    updated = store.start_fresh_session("sess_001", device_id="robot_02")
    frames_dir = tmp_path / "state" / "sessions" / "sess_001" / "frames"

    assert updated.device_id == "robot_02"
    assert updated.latest_result is None
    assert updated.result_history == []
    assert updated.conversation_history == []
    assert "recent_frames" not in store.session_payload("sess_001")
    assert not frames_dir.exists()
