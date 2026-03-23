from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Example Python websocket client for robot partners.",
    )
    parser.add_argument(
        "--backend-base-url",
        default="http://127.0.0.1:8001",
        help="Backend base URL, for example http://114.111.24.158:8001",
    )
    parser.add_argument(
        "--ws-url",
        default="",
        help="Optional explicit websocket URL. Overrides --backend-base-url.",
    )
    parser.add_argument(
        "--protocol",
        choices=("robot-agent", "robot-ingest"),
        default="robot-agent",
        help="Websocket protocol to use. Defaults to robot-agent.",
    )
    parser.add_argument(
        "--function",
        choices=("tracking", "chat"),
        default="tracking",
        help="robot-agent function. robot-ingest only supports tracking-like frame ingest.",
    )
    parser.add_argument(
        "--session-id",
        default=generate_session_id("partner_demo"),
        help="Session ID. Defaults to a generated value.",
    )
    parser.add_argument(
        "--request-id",
        default="",
        help="Request ID for robot-agent. Defaults to a generated value.",
    )
    parser.add_argument(
        "--device-id",
        default="robot_demo_01",
        help="Robot device ID.",
    )
    parser.add_argument(
        "--frame-id",
        default="frame_demo_000001",
        help="Frame ID for tracking requests.",
    )
    parser.add_argument(
        "--timestamp-ms",
        type=int,
        default=0,
        help="Frame timestamp in milliseconds. Defaults to current time.",
    )
    parser.add_argument(
        "--text",
        default="继续跟踪黑衣服的人",
        help="Natural language instruction or chat text.",
    )
    parser.add_argument(
        "--image",
        default="",
        help="Path to a local image file. Required for tracking requests.",
    )
    parser.add_argument(
        "--detections-json",
        default="",
        help='Inline detections JSON, for example \'[{"track_id":12,"bbox":[10,20,30,40],"score":0.95}]\'',
    )
    parser.add_argument(
        "--detections-file",
        default="",
        help="Path to a JSON file containing detection objects.",
    )
    parser.add_argument(
        "--connect-timeout-seconds",
        type=float,
        default=15.0,
        help="Websocket connect timeout.",
    )
    parser.add_argument(
        "--receive-timeout-seconds",
        type=float,
        default=0.0,
        help="Optional websocket receive timeout. Use 0 to wait indefinitely for a protocol response.",
    )
    return parser.parse_args()


def _now_ms() -> int:
    return round(time.time() * 1000)


def generate_session_id(prefix: str = "session") -> str:
    return f"{prefix}_{_now_ms()}"


def generate_request_id(prefix: str = "req") -> str:
    return f"{prefix}_{_now_ms()}"


def normalize_base_url(base_url: str, *, default_scheme: str = "http") -> str:
    cleaned = str(base_url).strip()
    if not cleaned:
        raise ValueError("base_url must not be empty")
    if "://" not in cleaned:
        cleaned = f"{default_scheme}://{cleaned}"
    parsed = urlsplit(cleaned)
    if not parsed.netloc:
        raise ValueError(f"base_url must include a host: {base_url!r}")
    normalized_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, normalized_path, "", ""))


def build_backend_service_url(base_url: str, *, protocol: str) -> str:
    normalized_base = normalize_base_url(base_url)
    parsed = urlsplit(normalized_base)
    scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    suffix = "/ws/robot-agent" if protocol == "robot-agent" else "/ws/robot-ingest"
    path = f"{parsed.path}{suffix}" if parsed.path else suffix
    return urlunsplit((scheme, parsed.netloc, path, "", ""))


def _load_image_base64(image_path: str) -> str:
    if not image_path:
        raise ValueError("--image is required for tracking requests")
    image_bytes = Path(image_path).read_bytes()
    return base64.b64encode(image_bytes).decode("ascii")


def _default_detections() -> list[dict[str, Any]]:
    return [
        {
            "track_id": 12,
            "bbox": [10, 20, 30, 40],
            "score": 0.95,
            "label": "person",
        }
    ]


def _load_detections(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.detections_file:
        return json.loads(Path(args.detections_file).read_text(encoding="utf-8"))
    if args.detections_json:
        return json.loads(args.detections_json)
    return _default_detections()


def build_ws_url(args: argparse.Namespace) -> str:
    if args.ws_url.strip():
        return args.ws_url.strip()
    return build_backend_service_url(args.backend_base_url, protocol=args.protocol)


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    timestamp_ms = args.timestamp_ms or _now_ms()
    detections = _load_detections(args)

    if args.protocol == "robot-ingest":
        if args.function != "tracking":
            raise ValueError("robot-ingest only supports tracking-style frame ingest")
        return {
            "session_id": args.session_id,
            "device_id": args.device_id,
            "frame": {
                "frame_id": args.frame_id,
                "timestamp_ms": timestamp_ms,
                "image_base64": _load_image_base64(args.image),
            },
            "detections": detections,
            "text": args.text,
        }

    request_id = args.request_id.strip() or generate_request_id("partner_req")
    payload: dict[str, Any] = {
        "request_id": request_id,
        "session_id": args.session_id,
        "function": args.function,
        "text": args.text,
    }
    if args.function == "tracking":
        payload.update(
            {
                "frame_id": args.frame_id,
                "timestamp_ms": timestamp_ms,
                "device_id": args.device_id,
                "image_base64": _load_image_base64(args.image),
                "detections": detections,
            }
        )
    return payload


async def run_client(args: argparse.Namespace) -> None:
    try:
        from websockets.client import connect
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: websockets. Install it with `pip install websockets`."
        ) from exc

    ws_url = build_ws_url(args)
    payload = build_payload(args)

    print(f"Connecting to: {ws_url}")
    print("Sending payload:")
    print(json.dumps(payload, ensure_ascii=True, indent=2))

    async with connect(
        ws_url,
        open_timeout=args.connect_timeout_seconds,
        close_timeout=min(args.connect_timeout_seconds, 10.0),
        ping_interval=20,
        ping_timeout=max(args.connect_timeout_seconds, 20.0),
        max_size=None,
    ) as websocket:
        await asyncio.wait_for(
            websocket.send(json.dumps(payload, ensure_ascii=False)),
            timeout=args.connect_timeout_seconds,
        )

        if args.protocol == "robot-agent":
            expected_request_id = str(payload["request_id"])
            while True:
                try:
                    response_raw = await _recv_with_optional_timeout(
                        websocket,
                        args.receive_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    print(
                        "No websocket response was received before the local client timeout. "
                        "This does not mean the protocol timed out on the server side. "
                        f"Increase --receive-timeout-seconds or use 0 to wait indefinitely. request_id={expected_request_id}"
                    )
                    return
                response = json.loads(response_raw)
                if str(response.get("request_id", "")) != expected_request_id:
                    print("Ignoring stale response for a different request_id:")
                    print(json.dumps(response, ensure_ascii=True, indent=2))
                    continue
                print("Received response:")
                print(json.dumps(response, ensure_ascii=True, indent=2))
                return

        while True:
            try:
                response_raw = await _recv_with_optional_timeout(
                    websocket,
                    args.receive_timeout_seconds,
                )
            except asyncio.TimeoutError:
                print(
                    "No websocket event was received before the local client timeout. "
                    "This does not mean the protocol timed out on the server side. "
                    f"Increase --receive-timeout-seconds or use 0 to wait indefinitely."
                )
                return
            response = json.loads(response_raw)
            print("Received event:")
            print(json.dumps(response, ensure_ascii=True, indent=2))
            if response.get("type") in {"robot_ingest_result", "robot_ingest_error"}:
                return


async def _recv_with_optional_timeout(websocket: Any, timeout_seconds: float) -> str:
    if timeout_seconds <= 0:
        return await websocket.recv()
    return await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)


def main() -> None:
    args = parse_args()
    asyncio.run(run_client(args))


if __name__ == "__main__":
    main()
