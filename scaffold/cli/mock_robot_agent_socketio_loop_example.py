from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path

import socketio


BASE_URL = "http://114.111.24.158:8001"
IMAGE_PATH = "./frame.jpg"
SESSION_ID = "sess_demo_001"
DEVICE_ID = "robot_01"
INTERVAL_SECONDS = 3.0
TOTAL_REQUESTS = 5

# 二选一即可：
# INITIAL_TEXT = "请跟踪ID为12的人"
INITIAL_TEXT = "请跟踪穿黑衣服的人"
ONGOING_TEXT = "继续跟踪"

# mock 检测框。真实接入时替换成 robot 视觉模块的输出。
DETECTIONS = [
    {"track_id": 12, "bbox": [120, 80, 260, 420]},
    {"track_id": 15, "bbox": [300, 90, 430, 410]},
]


def now_ms() -> int:
    return int(time.time() * 1000)


def request_id() -> str:
    return f"req_{now_ms()}"


def frame_id(index: int) -> str:
    return f"frame_{index:06d}"


def load_image_base64() -> str:
    return base64.b64encode(Path(IMAGE_PATH).read_bytes()).decode("ascii")


def build_payload(
    *,
    frame_index: int,
    text: str,
    image_base64: str,
) -> dict:
    return {
        "request_id": request_id(),
        "session_id": SESSION_ID,
        "function": "tracking",
        "frame_id": frame_id(frame_index),
        "timestamp_ms": now_ms(),
        "device_id": DEVICE_ID,
        "image_base64": image_base64,
        "detections": DETECTIONS,
        "text": text,
    }


async def send_tracking_request(
    client: socketio.AsyncClient,
    *,
    frame_index: int,
    text: str,
    image_base64: str,
) -> None:
    payload = build_payload(
        frame_index=frame_index,
        text=text,
        image_base64=image_base64,
    )
    print(f"\nSending frame={payload['frame_id']} text={payload['text']}")
    response = await client.call("robot-agent-request", payload, timeout=60)
    print("Received:", response)


async def main() -> None:
    image_base64 = load_image_base64()
    client = socketio.AsyncClient()
    await client.connect(BASE_URL, socketio_path="socket.io")
    try:
        await send_tracking_request(
            client,
            frame_index=1,
            text=INITIAL_TEXT,
            image_base64=image_base64,
        )

        for index in range(2, TOTAL_REQUESTS + 1):
            await asyncio.sleep(INTERVAL_SECONDS)
            await send_tracking_request(
                client,
                frame_index=index,
                text=ONGOING_TEXT,
                image_base64=image_base64,
            )
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
