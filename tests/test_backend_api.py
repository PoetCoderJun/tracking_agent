from __future__ import annotations

import base64
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

import tracking_agent.backend_api as backend_api


def _fake_image_base64() -> str:
    return base64.b64encode(b"fake-image-bytes").decode("ascii")


def test_websocket_receives_updates_when_robot_event_arrives(
    tmp_path: Path,
) -> None:
    with TestClient(backend_api.create_app(state_root=tmp_path / "state")) as client:
        with client.websocket_connect("/ws/session-events") as websocket:
            connected = websocket.receive_json()
            assert connected == {"type": "connected"}
            snapshot = websocket.receive_json()
            assert snapshot["type"] == "dashboard_state"
            assert snapshot["frontend_state"] is None
            assert snapshot["sessions"] == []

            response = client.post(
                "/api/v1/robot/ingest",
                json={
                    "session_id": "sess_001",
                    "device_id": "robot_01",
                    "frame": {
                        "frame_id": "frame_000001",
                        "timestamp_ms": 1710000000000,
                        "image_base64": _fake_image_base64(),
                    },
                    "detections": [
                        {"track_id": 12, "bbox": [10, 20, 30, 40], "score": 0.95},
                    ],
                    "text": "跟踪黑衣服的人",
                },
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["agent_required"] is True
            assert payload["agent_behavior"] is None
            assert payload["session_path"] == "/api/v1/sessions/sess_001"
            event = websocket.receive_json()

    assert event["type"] == "session_update"
    assert event["source"] == "ingest"
    assert event["session_id"] == "sess_001"
    assert event["changed_session_id"] == "sess_001"
    assert event["frontend_state"]["session_id"] == "sess_001"
    assert event["sessions"][0]["session_id"] == "sess_001"


def test_robot_ingest_websocket_returns_same_response_shape(tmp_path: Path) -> None:
    with TestClient(backend_api.create_app(state_root=tmp_path / "state")) as client:
        with client.websocket_connect("/ws/robot-ingest") as websocket:
            websocket.send_json(
                {
                    "session_id": "sess_001",
                    "device_id": "robot_01",
                    "frame": {
                        "frame_id": "frame_000001",
                        "timestamp_ms": 1710000000000,
                        "image_base64": _fake_image_base64(),
                    },
                    "detections": [
                        {"track_id": 12, "bbox": [10, 20, 30, 40], "score": 0.95},
                    ],
                    "text": "跟踪黑衣服的人",
                }
            )
            payload = websocket.receive_json()

    assert payload["type"] == "robot_ingest_result"
    assert payload["status"] == 200
    assert payload["payload"]["session_id"] == "sess_001"
    assert payload["payload"]["agent_required"] is True


def test_agent_result_accepts_external_pi_fields(tmp_path: Path) -> None:
    with TestClient(backend_api.create_app(state_root=tmp_path / "state")) as client:
        ingest = client.post(
            "/api/v1/robot/ingest",
            json={
                "session_id": "sess_001",
                "device_id": "robot_01",
                "frame": {
                    "frame_id": "frame_000001",
                    "timestamp_ms": 1710000000000,
                    "image_base64": _fake_image_base64(),
                },
                "detections": [
                    {"track_id": 12, "bbox": [10, 20, 30, 40], "score": 0.95},
                ],
                "text": "跟踪黑衣服的人",
            },
        )
        assert ingest.status_code == 200

        result = client.post(
            "/api/v1/sessions/sess_001/agent-result",
            json={
                "behavior": "init",
                "frame_id": "frame_000001",
                "text": "我确认当前目标是 12。",
                "target_id": 12,
                "found": True,
                "needs_clarification": False,
                "clarification_question": None,
                "memory": "短发，黑衣服。",
                "target_description": "黑衣服的人",
                "pending_question": None,
                "latest_target_crop": "/tmp/crop.jpg",
            },
        )
        assert result.status_code == 200

        state = client.get("/api/v1/sessions/sess_001/frontend-state")
        assert state.status_code == 200
        payload = state.json()

    assert payload["target_description"] == "黑衣服的人"
    assert payload["latest_target_id"] == 12
    assert payload["latest_result"]["behavior"] == "init"
    assert payload["latest_result"]["frame_id"] == "frame_000001"


def test_frontend_state_hides_display_frame_until_target_is_confirmed(tmp_path: Path) -> None:
    with TestClient(backend_api.create_app(state_root=tmp_path / "state")) as client:
        ingest = client.post(
            "/api/v1/robot/ingest",
            json={
                "session_id": "sess_001",
                "device_id": "robot_01",
                "frame": {
                    "frame_id": "frame_000001",
                    "timestamp_ms": 1710000000000,
                    "image_base64": _fake_image_base64(),
                },
                "detections": [
                    {"track_id": 12, "bbox": [10, 20, 30, 40], "score": 0.95},
                ],
                "text": "跟踪黑衣服的人",
            },
        )
        assert ingest.status_code == 200

        state = client.get("/api/v1/sessions/sess_001/frontend-state")
        assert state.status_code == 200
        payload = state.json()

    assert payload["latest_frame"]["frame_id"] == "frame_000001"
    assert payload["display_frame"] is None


def test_frontend_state_keeps_last_confirmed_display_frame_until_next_confirmed_frame(
    tmp_path: Path,
) -> None:
    with TestClient(backend_api.create_app(state_root=tmp_path / "state")) as client:
        ingest_first = client.post(
            "/api/v1/robot/ingest",
            json={
                "session_id": "sess_001",
                "device_id": "robot_01",
                "frame": {
                    "frame_id": "frame_000001",
                    "timestamp_ms": 1710000000000,
                    "image_base64": _fake_image_base64(),
                },
                "detections": [
                    {"track_id": 12, "bbox": [10, 20, 30, 40], "score": 0.95},
                ],
                "text": "跟踪黑衣服的人",
            },
        )
        assert ingest_first.status_code == 200

        first_result = client.post(
            "/api/v1/sessions/sess_001/agent-result",
            json={
                "behavior": "init",
                "frame_id": "frame_000001",
                "text": "我确认当前目标是 12。",
                "target_id": 12,
                "found": True,
                "needs_clarification": False,
                "clarification_question": None,
                "memory": "短发，黑衣服。",
            },
        )
        assert first_result.status_code == 200

        ingest_second = client.post(
            "/api/v1/robot/ingest",
            json={
                "session_id": "sess_001",
                "device_id": "robot_01",
                "frame": {
                    "frame_id": "frame_000002",
                    "timestamp_ms": 1710000003000,
                    "image_base64": _fake_image_base64(),
                },
                "detections": [
                    {"track_id": 12, "bbox": [12, 22, 32, 42], "score": 0.94},
                ],
                "text": "持续跟踪",
            },
        )
        assert ingest_second.status_code == 200

        missing_result = client.post(
            "/api/v1/sessions/sess_001/agent-result",
            json={
                "behavior": "track",
                "frame_id": "frame_000002",
                "text": "当前帧没有可靠找到目标。",
                "target_id": 12,
                "found": False,
                "needs_clarification": False,
                "clarification_question": None,
                "memory": "短发，黑衣服。",
            },
        )
        assert missing_result.status_code == 200

        state = client.get("/api/v1/sessions/sess_001/frontend-state")
        assert state.status_code == 200
        payload = state.json()

        image = client.get(payload["display_frame"]["image_url"])
        assert image.status_code == 200

    assert payload["latest_frame"]["frame_id"] == "frame_000002"
    assert payload["latest_result"]["frame_id"] == "frame_000002"
    assert payload["latest_result"]["found"] is False
    assert payload["display_frame"]["frame_id"] == "frame_000001"
    assert payload["display_frame"]["bbox"] == [10, 20, 30, 40]
    assert payload["display_frame"]["target_id"] == 12


def test_session_endpoint_returns_raw_backend_state(tmp_path: Path) -> None:
    with TestClient(backend_api.create_app(state_root=tmp_path / "state")) as client:
        ingest = client.post(
            "/api/v1/robot/ingest",
            json={
                "session_id": "sess_001",
                "device_id": "robot_01",
                "frame": {
                    "frame_id": "frame_000001",
                    "timestamp_ms": 1710000000000,
                    "image_base64": _fake_image_base64(),
                },
                "detections": [
                    {"track_id": 12, "bbox": [10, 20, 30, 40], "score": 0.95},
                ],
                "text": "跟踪黑衣服的人",
            },
        )
        assert ingest.status_code == 200

        result = client.post(
            "/api/v1/sessions/sess_001/agent-result",
            json={
                "behavior": "init",
                "text": "我确认当前目标是 12。",
                "bounding_box_id": 12,
                "found": True,
                "needs_clarification": False,
                "clarification_question": None,
                "memory": "短发，黑衣服。",
                "target_description": "黑衣服的人",
                "pending_question": None,
                "latest_target_crop": "/tmp/crop.jpg",
            },
        )
        assert result.status_code == 200

        session = client.get("/api/v1/sessions/sess_001")
        assert session.status_code == 200
        session_payload = session.json()

    assert "latest_bounding_box_id" not in session_payload
    assert session_payload["latest_result"]["target_id"] == 12
    assert "bounding_box_id" not in session_payload["latest_result"]
    assert session_payload["recent_frames"][-1]["detections"][0]["track_id"] == 12


def test_ingest_waits_for_external_agent_result_before_replying(tmp_path: Path) -> None:
    with TestClient(backend_api.create_app(
        state_root=tmp_path / "state",
        external_agent_wait_seconds=1.0,
        external_agent_poll_seconds=0.01,
    )) as client:
        response_holder: dict[str, object] = {}
        ingest_done = threading.Event()

        def post_ingest() -> None:
            response = client.post(
                "/api/v1/robot/ingest",
                json={
                    "session_id": "sess_001",
                    "device_id": "robot_01",
                    "frame": {
                        "frame_id": "frame_000001",
                        "timestamp_ms": 1710000000000,
                        "image_base64": _fake_image_base64(),
                    },
                    "detections": [
                        {"track_id": 12, "bbox": [10, 20, 30, 40], "score": 0.95},
                    ],
                    "text": "跟踪黑衣服的人",
                },
            )
            response_holder["status_code"] = response.status_code
            response_holder["payload"] = response.json()
            ingest_done.set()

        worker = threading.Thread(target=post_ingest)
        worker.start()

        time.sleep(0.05)
        assert ingest_done.is_set() is False

        result = client.post(
            "/api/v1/sessions/sess_001/agent-result",
            json={
                "behavior": "init",
                "text": "我确认当前目标是 12。",
                "target_id": 12,
                "found": True,
                "needs_clarification": False,
                "clarification_question": None,
                "memory": "短发，黑衣服。",
                "target_description": "黑衣服的人",
                "pending_question": None,
                "latest_target_crop": "/tmp/crop.jpg",
            },
        )

        assert result.status_code == 200
        assert ingest_done.wait(1.0) is True
        worker.join(timeout=1.0)

    assert response_holder["status_code"] == 200
    payload = response_holder["payload"]
    assert isinstance(payload, dict)
    assert payload["agent_required"] is False
    assert payload["agent_behavior"] == "init"
    assert payload["latest_target_id"] == 12
    assert payload["latest_result"]["frame_id"] == "frame_000001"


def test_memory_update_endpoint_rewrites_latest_memory(tmp_path: Path) -> None:
    with TestClient(backend_api.create_app(state_root=tmp_path / "state")) as client:
        ingest = client.post(
            "/api/v1/robot/ingest",
            json={
                "session_id": "sess_001",
                "device_id": "robot_01",
                "frame": {
                    "frame_id": "frame_000001",
                    "timestamp_ms": 1710000000000,
                    "image_base64": _fake_image_base64(),
                },
                "detections": [
                    {"track_id": 12, "bbox": [10, 20, 30, 40], "score": 0.95},
                ],
                "text": "跟踪黑衣服的人",
            },
        )
        assert ingest.status_code == 200

        result = client.post(
            "/api/v1/sessions/sess_001/agent-result",
            json={
                "behavior": "track",
                "frame_id": "frame_000001",
                "text": "我确认当前目标是 12。",
                "target_id": 12,
                "found": True,
                "memory": "",
            },
        )
        assert result.status_code == 200

        memory_update = client.post(
            "/api/v1/sessions/sess_001/memory-update",
            json={
                "memory": "更新后的 memory",
                "expected_frame_id": "frame_000001",
                "expected_target_id": 12,
                "expected_target_crop": None,
            },
        )
        assert memory_update.status_code == 200

        state = client.get("/api/v1/sessions/sess_001/frontend-state")
        assert state.status_code == 200

    payload = state.json()
    assert payload["latest_memory"] == "更新后的 memory"
    assert payload["latest_result"]["memory"] == "更新后的 memory"
