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
    app = backend_api.create_app(state_root=tmp_path / "state", env_path=tmp_path / ".ENV")

    with TestClient(app) as client:
        with client.websocket_connect("/ws/frontend-updates") as websocket:
            connected = websocket.receive_json()
            assert connected == {"type": "connected"}

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
            assert payload["agent_context"]["session_id"] == "sess_001"
            event = websocket.receive_json()

    assert event["type"] == "session_update"
    assert event["source"] == "ingest"
    assert event["session_id"] == "sess_001"


def test_ingest_auto_runs_agent_and_rewrites_memory(tmp_path: Path) -> None:
    class FakeAgent:
        def run(self, session, session_dir: Path, text: str):
            assert session.session_id == "sess_001"
            assert text == "跟踪黑衣服的人"
            return {
                "behavior": "init",
                "text": "我确认当前目标是 12。",
                "target_id": 12,
                "found": True,
                "needs_clarification": False,
                "clarification_question": None,
                "memory": "",
                "target_description": "黑衣服的人",
                "pending_question": None,
                "latest_target_crop": str(session_dir / "reference_crops" / "frame_000001_id_12.jpg"),
                "memory_rewrite": {
                    "task": "init",
                    "crop_path": str(session_dir / "reference_crops" / "frame_000001_id_12.jpg"),
                    "frame_paths": [str(session_dir / "frames" / "frame_000001.jpg")],
                    "frame_id": "frame_000001",
                    "target_id": 12,
                },
            }

        def rewrite_memory(self, request) -> str:
            assert request.frame_id == "frame_000001"
            assert request.target_id == 12
            return "短发，黑衣服。"

    app = backend_api.create_app(
        state_root=tmp_path / "state",
        env_path=tmp_path / ".ENV",
        agent_factory=lambda _: FakeAgent(),
    )

    with TestClient(app) as client:
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
        assert payload["agent_required"] is False
        assert payload["agent_error"] is None
        assert payload["agent_behavior"] == "init"
        assert payload["latest_target_id"] == 12
        assert payload["latest_memory"] == "短发，黑衣服。"
        assert payload["latest_result"]["found"] is True
        assert payload["latest_result"]["bbox"] == [10, 20, 30, 40]

        state = client.get("/api/v1/sessions/sess_001/frontend-state")
        assert state.status_code == 200
        state_payload = state.json()

    assert state_payload["latest_memory"] == "短发，黑衣服。"
    assert state_payload["latest_result"]["text"] == "我确认当前目标是 12。"
    assert state_payload["conversation_history"][-1]["role"] == "assistant"


def test_run_agent_endpoint_requires_external_pi_agent(tmp_path: Path) -> None:
    app = backend_api.create_app(state_root=tmp_path / "state", env_path=tmp_path / ".ENV")

    with TestClient(app) as client:
        response = client.post("/api/v1/sessions/sess_001/run-agent", json={"text": "继续跟踪"})

    assert response.status_code == 410
    assert "PI Agent" in response.json()["detail"]


def test_agent_result_accepts_external_pi_fields(tmp_path: Path) -> None:
    app = backend_api.create_app(state_root=tmp_path / "state", env_path=tmp_path / ".ENV")

    with TestClient(app) as client:
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


def test_agent_result_accepts_bounding_box_id_alias(tmp_path: Path) -> None:
    app = backend_api.create_app(state_root=tmp_path / "state", env_path=tmp_path / ".ENV")

    with TestClient(app) as client:
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

        context = client.get("/api/v1/sessions/sess_001/agent-context")
        assert context.status_code == 200
        context_payload = context.json()

    assert context_payload["latest_bounding_box_id"] == 12
    assert context_payload["latest_result"]["bounding_box_id"] == 12
    assert context_payload["frames"][-1]["detections"][0]["bounding_box_id"] == 12


def test_ingest_waits_for_external_agent_result_before_replying(tmp_path: Path) -> None:
    app = backend_api.create_app(
        state_root=tmp_path / "state",
        env_path=tmp_path / ".ENV",
        auto_run_agent=False,
        external_agent_wait_seconds=1.0,
        external_agent_poll_seconds=0.01,
    )

    response_holder: dict[str, object] = {}
    ingest_done = threading.Event()

    with TestClient(app) as client:
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
