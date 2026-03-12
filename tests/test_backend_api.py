from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

import tracking_agent.backend_api as backend_api


def _fake_image_base64() -> str:
    return base64.b64encode(b"fake-image-bytes").decode("ascii")


class DummyAgent:
    def __init__(self, env_path: Path):
        self._env_path = env_path

    def run(self, session, session_dir: Path, text: str) -> dict:
        return {
            "behavior": "reply",
            "text": f"echo:{text}",
            "target_id": None,
            "found": False,
            "needs_clarification": False,
            "clarification_question": None,
            "memory": session.latest_memory,
            "latest_target_crop": session.latest_target_crop,
            "pending_question": None,
        }

    def rewrite_memory(self, request) -> str:
        return "rewritten-memory"


def test_websocket_receives_updates_when_robot_event_arrives(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(backend_api, "CloudTrackingAgent", DummyAgent)
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
            event = websocket.receive_json()

    assert event["type"] == "session_update"
    assert event["source"] in {"ingest", "agent_result"}
    assert event["session_id"] == "sess_001"
