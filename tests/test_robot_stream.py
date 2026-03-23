from __future__ import annotations

import asyncio
import json
from pathlib import Path

from PIL import Image

from tracking_agent.robot_stream import (
    RobotDetection,
    RobotFrame,
    RobotIngestEvent,
    SOCKETIO_ROBOT_AGENT_EVENT,
    append_event_jsonl,
    event_payload,
    generate_request_id,
    generate_session_id,
    is_camera_source,
    is_websocket_url,
    normalize_source,
    parse_frame_rate,
    post_event_socketio,
    post_event_ws,
    robot_agent_request_payload,
    video_timestamp_seconds,
)


def test_normalize_source_supports_camera_index() -> None:
    assert normalize_source("0") == 0
    assert normalize_source(" 12 ") == 12
    assert normalize_source("test_data/0045.mp4") == "test_data/0045.mp4"
    assert is_camera_source(normalize_source("0")) is True
    assert is_camera_source(normalize_source("test_data/0045.mp4")) is False


def test_generate_session_id_returns_unique_prefixed_value() -> None:
    session_id_a = generate_session_id()
    session_id_b = generate_session_id()

    assert session_id_a.startswith("session_")
    assert session_id_b.startswith("session_")
    assert session_id_a != session_id_b


def test_generate_request_id_returns_unique_prefixed_value() -> None:
    request_id_a = generate_request_id()
    request_id_b = generate_request_id()

    assert request_id_a.startswith("req_")
    assert request_id_b.startswith("req_")
    assert request_id_a != request_id_b


def test_is_websocket_url_detects_ws_and_wss() -> None:
    assert is_websocket_url("ws://127.0.0.1:8001/ws/robot-ingest") is True
    assert is_websocket_url("wss://example.com/ws/robot-ingest") is True
    assert is_websocket_url("http://127.0.0.1:8001/api/v1/robot/ingest") is False


def test_parse_frame_rate_supports_fractional_ffprobe_output() -> None:
    assert parse_frame_rate("30000/1001") == 30000 / 1001
    assert parse_frame_rate("25") == 25.0


def test_video_timestamp_seconds_uses_zero_based_video_time() -> None:
    assert video_timestamp_seconds(frame_index=1, fps=30.0) == 0.0
    assert video_timestamp_seconds(frame_index=91, fps=30.0) == 3.0


def test_append_event_jsonl_writes_serialized_event(tmp_path: Path) -> None:
    event = RobotIngestEvent(
        session_id="sess_001",
        device_id="robot_01",
        frame=RobotFrame(
            frame_id="frame_000001",
            timestamp_ms=1710000000000,
            image_path=str(tmp_path / "frame_000001.jpg"),
        ),
        detections=[
            RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95),
        ],
        text="继续跟踪",
    )

    output_path = tmp_path / "events.jsonl"
    append_event_jsonl(output_path, event)

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["session_id"] == "sess_001"
    assert payload["detections"][0]["track_id"] == 12
    assert payload["frame"]["image_path"].endswith("frame_000001.jpg")


def test_event_payload_can_inline_image_base64(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.jpg"
    Image.new("RGB", (8, 8), color="white").save(image_path, format="JPEG")

    event = RobotIngestEvent(
        session_id="sess_001",
        device_id="robot_01",
        frame=RobotFrame(
            frame_id="frame_000001",
            timestamp_ms=1710000000000,
            image_path=str(image_path),
        ),
        detections=[],
        text="",
    )

    payload = event_payload(event, include_image_base64=True)

    assert payload["frame"]["image_path"] == str(image_path)
    assert isinstance(payload["frame"]["image_base64"], str)
    assert payload["frame"]["image_base64"]


def test_robot_agent_request_payload_flattens_tracking_fields(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.jpg"
    Image.new("RGB", (8, 8), color="white").save(image_path, format="JPEG")

    event = RobotIngestEvent(
        session_id="sess_001",
        device_id="robot_01",
        frame=RobotFrame(
            frame_id="frame_000001",
            timestamp_ms=1710000000000,
            image_path=str(image_path),
        ),
        detections=[RobotDetection(track_id=12, bbox=[10, 20, 30, 40], score=0.95)],
        text="继续跟踪",
    )

    payload = robot_agent_request_payload(event, request_id="req_001", function="tracking")

    assert payload["request_id"] == "req_001"
    assert payload["function"] == "tracking"
    assert payload["frame_id"] == "frame_000001"
    assert payload["device_id"] == "robot_01"
    assert payload["detections"][0]["track_id"] == 12
    assert isinstance(payload["image_base64"], str)
    assert payload["image_base64"]


def test_post_event_ws_consumes_ack_and_status_before_final_result(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.jpg"
    Image.new("RGB", (8, 8), color="white").save(image_path, format="JPEG")
    event = RobotIngestEvent(
        session_id="sess_001",
        device_id="robot_01",
        frame=RobotFrame(
            frame_id="frame_000001",
            timestamp_ms=1710000000000,
            image_path=str(image_path),
        ),
        detections=[],
        text="",
    )

    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent_messages = []
            self._responses = iter(
                [
                    json.dumps({"type": "robot_ingest_ack", "status": 202, "session_id": "sess_001"}),
                    json.dumps({"type": "robot_ingest_status", "status": 202, "stage": "waiting_for_agent"}),
                    json.dumps({"type": "robot_ingest_result", "status": 200, "payload": {"agent_required": True}}),
                ]
            )

        async def send(self, message: str) -> None:
            self.sent_messages.append(json.loads(message))

        async def recv(self) -> str:
            return next(self._responses)

    observed_events = []
    response = asyncio.run(
        post_event_ws(
            FakeWebSocket(),
            event,
            timeout_seconds=1.0,
            on_event=lambda payload: observed_events.append(payload["type"]),
        )
    )

    assert observed_events == ["robot_ingest_ack", "robot_ingest_status", "robot_ingest_result"]
    assert response["status"] == 200
    assert json.loads(response["body"])["agent_required"] is True


def test_post_event_ws_supports_robot_agent_protocol(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.jpg"
    Image.new("RGB", (8, 8), color="white").save(image_path, format="JPEG")
    event = RobotIngestEvent(
        session_id="sess_001",
        device_id="robot_01",
        frame=RobotFrame(
            frame_id="frame_000001",
            timestamp_ms=1710000000000,
            image_path=str(image_path),
        ),
        detections=[],
        text="继续跟踪",
    )

    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent_messages = []
            self._responses = iter(
                [
                    json.dumps(
                        {
                            "request_id": "req_001",
                            "session_id": "sess_001",
                            "function": "tracking",
                            "frame_id": "frame_000001",
                            "action": "wait",
                            "text": "等待云端结果。",
                        }
                    ),
                ]
            )

        async def send(self, message: str) -> None:
            self.sent_messages.append(json.loads(message))

        async def recv(self) -> str:
            return next(self._responses)

    response = asyncio.run(
        post_event_ws(
            FakeWebSocket(),
            event,
            timeout_seconds=1.0,
            request_id="req_001",
            function="tracking",
            protocol="robot_agent",
        )
    )

    payload = json.loads(response["body"])
    assert response["status"] == 200
    assert payload["request_id"] == "req_001"
    assert payload["action"] == "wait"


def test_post_event_socketio_calls_robot_agent_event(tmp_path: Path) -> None:
    image_path = tmp_path / "frame.jpg"
    Image.new("RGB", (8, 8), color="white").save(image_path, format="JPEG")
    event = RobotIngestEvent(
        session_id="sess_001",
        device_id="robot_01",
        frame=RobotFrame(
            frame_id="frame_000001",
            timestamp_ms=1710000000000,
            image_path=str(image_path),
        ),
        detections=[],
        text="继续跟踪",
    )

    class FakeSocketIOClient:
        def __init__(self) -> None:
            self.calls = []

        async def call(self, event_name: str, payload: dict, timeout: float):
            self.calls.append((event_name, payload, timeout))
            return {
                "request_id": "req_001",
                "session_id": "sess_001",
                "function": "tracking",
                "frame_id": "frame_000001",
                "action": "wait",
                "text": "等待云端结果。",
            }

    client = FakeSocketIOClient()
    response = asyncio.run(
        post_event_socketio(
            client,
            event,
            timeout_seconds=1.0,
            request_id="req_001",
            function="tracking",
        )
    )

    assert client.calls[0][0] == SOCKETIO_ROBOT_AGENT_EVENT
    assert client.calls[0][1]["request_id"] == "req_001"
    assert response["status"] == 200
    assert json.loads(response["body"])["action"] == "wait"
