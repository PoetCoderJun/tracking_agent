from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from pathlib import Path

from websockets.client import connect


WS_URL = "ws://114.111.24.158:8001/ws/robot-agent"
IMAGE_PATH = "./frame.jpg"
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

    async with connect(WS_URL, max_size=None) as ws:
        await ws.send(json.dumps(payload, ensure_ascii=False))
        response = json.loads(await ws.recv())
        print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
