from __future__ import annotations

import asyncio
import base64
import time
import uuid
from pathlib import Path

import socketio


BASE_URL = "http://114.111.24.158:8001"
IMAGE_PATH = "./frame.jpg"
EVENT_NAME = "robot-agent-request"
SESSION_ID = f"sess_demo_{uuid.uuid4().hex[:12]}"


async def main() -> None:
    image_base64 = base64.b64encode(Path(IMAGE_PATH).read_bytes()).decode("ascii")

    payload = {
        "request_id": f"req_{int(time.time() * 1000)}",
        "session_id": SESSION_ID,
        "function": "tracking",
        "frame_id": "frame_000001",
        "timestamp_ms": int(time.time() * 1000),
        "device_id": "robot_01",
        "image_base64": image_base64,
        "detections": [
            {"track_id": 12, "bbox": [120, 80, 260, 420]},
            {"track_id": 15, "bbox": [300, 90, 430, 410]},
        ],
        "text": "继续跟踪刚才那个穿黑衣服的人",
    }

    client = socketio.AsyncClient()
    await client.connect(BASE_URL, socketio_path="socket.io")
    try:
        try:
            response = await client.call(EVENT_NAME, payload, timeout=60)
        except socketio.exceptions.TimeoutError:
            print(
                {
                    "session_id": SESSION_ID,
                    "request_id": payload["request_id"],
                    "status": "timeout",
                    "message": "Backend accepted the request but did not return a socket.io response within 60 seconds.",
                }
            )
            return
        print(response)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
