from __future__ import annotations

import aiohttp
import asyncio
import gzip
import json
import struct
import uuid
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, Optional

from .runtime_config import asr_settings, require_env

DEFAULT_SAMPLE_RATE = 16000

TRACKING_STT_WS_URL_ENV = "TRACKING_STT_WS_URL"
TRACKING_STT_APP_KEY_ENV = "TRACKING_STT_APP_KEY"
TRACKING_STT_ACCESS_KEY_ENV = "TRACKING_STT_ACCESS_KEY"


class MessageType:
    CLIENT_FULL_REQUEST = 0b0001
    CLIENT_AUDIO_ONLY_REQUEST = 0b0010
    SERVER_FULL_RESPONSE = 0b1001
    SERVER_ERROR_RESPONSE = 0b1111


class Flags:
    POS_SEQUENCE = 0x01
    NEG_NO_SEQUENCE = 0x02


def gzip_compress(data: bytes) -> bytes:
    return gzip.compress(data)


def gzip_decompress(data: bytes) -> bytes:
    return gzip.decompress(data)


def build_header(message_type: int, flags: int) -> bytes:
    return bytes(
        [
            (0b0001 << 4) | 1,
            (message_type << 4) | flags,
            (0b0001 << 4) | 0b0001,
            0x00,
        ]
    )


def build_auth_headers() -> Dict[str, str]:
    settings = asr_settings()
    return {
        "X-Api-Resource-Id": "volc.seedasr.sauc.duration",
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Access-Key": settings["access_key"],
        "X-Api-App-Key": settings["app_key"],
    }


def build_full_request(seq: int) -> bytes:
    payload = {
        "user": {"uid": "pointing_demo"},
        "audio": {
            "format": "pcm",
            "codec": "raw",
            "rate": DEFAULT_SAMPLE_RATE,
            "bits": 16,
            "channel": 1,
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": True,
            "show_utterances": True,
            "enable_nonstream": False,
        },
    }
    compressed = gzip_compress(json.dumps(payload).encode("utf-8"))
    return b"".join(
        [
            build_header(MessageType.CLIENT_FULL_REQUEST, Flags.POS_SEQUENCE),
            struct.pack(">i", seq),
            struct.pack(">I", len(compressed)),
            compressed,
        ]
    )


def build_audio_request(seq: int, segment: bytes, is_last: bool = False) -> bytes:
    header = build_header(
        MessageType.CLIENT_AUDIO_ONLY_REQUEST,
        Flags.NEG_NO_SEQUENCE if is_last else Flags.POS_SEQUENCE,
    )
    compressed = gzip_compress(segment)
    parts = [header]
    if not is_last:
        parts.append(struct.pack(">i", seq))
    parts.extend([struct.pack(">I", len(compressed)), compressed])
    return b"".join(parts)


@dataclass
class AsrResponse:
    code: int = 0
    event: int = 0
    is_last_package: bool = False
    payload_sequence: int = 0
    payload_size: int = 0
    payload_msg: Optional[Dict[str, Any]] = None


def parse_response(msg: bytes) -> AsrResponse:
    response = AsrResponse()

    header_size = msg[0] & 0x0F
    message_type = msg[1] >> 4
    flags = msg[1] & 0x0F
    serialization = msg[2] >> 4
    compression = msg[2] & 0x0F
    payload = msg[header_size * 4 :]

    if flags & 0x01:
        response.payload_sequence = struct.unpack(">i", payload[:4])[0]
        payload = payload[4:]
    if flags & 0x02:
        response.is_last_package = True
    if flags & 0x04:
        response.event = struct.unpack(">i", payload[:4])[0]
        payload = payload[4:]

    if message_type == MessageType.SERVER_FULL_RESPONSE:
        response.payload_size = struct.unpack(">I", payload[:4])[0]
        payload = payload[4:]
    elif message_type == MessageType.SERVER_ERROR_RESPONSE:
        response.code = struct.unpack(">i", payload[:4])[0]
        response.payload_size = struct.unpack(">I", payload[4:8])[0]
        payload = payload[8:]

    if payload and compression == 0b0001:
        payload = gzip_decompress(payload)
    if payload and serialization == 0b0001:
        response.payload_msg = json.loads(payload.decode("utf-8"))

    return response


class StreamingAsrClient:
    def __init__(self, url: Optional[str] = None, sample_rate: int = DEFAULT_SAMPLE_RATE):
        settings = asr_settings()
        resolved_url = str(url).strip() if url is not None else ""
        self.url = resolved_url or settings["ws_url"] or require_env(
            TRACKING_STT_WS_URL_ENV, "POINTING_STT_WS_URL"
        )
        self.sample_rate = sample_rate
        self.session: Optional[aiohttp.ClientSession] = None
        self.conn: Optional[aiohttp.ClientWebSocketResponse] = None
        self.seq = 1

    async def connect_and_init(self) -> None:
        self.session = aiohttp.ClientSession()
        try:
            self.conn = await self.session.ws_connect(self.url, headers=build_auth_headers())
            await self.conn.send_bytes(build_full_request(self.seq))
            self.seq += 1
            await self.conn.receive()
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        if self.conn is not None and not self.conn.closed:
            await self.conn.close()
        if self.session is not None and not self.session.closed:
            await self.session.close()
        self.conn = None
        self.session = None

    async def send_audio_chunk(self, pcm_chunk: bytes, is_last: bool = False) -> None:
        if self.conn is None or self.conn.closed:
            raise RuntimeError("ASR websocket not connected")
        await self.conn.send_bytes(build_audio_request(self.seq, pcm_chunk, is_last=is_last))
        if not is_last:
            self.seq += 1

    async def recv_loop(self, on_result=None) -> AsyncGenerator[AsrResponse, None]:
        if self.conn is None or self.conn.closed:
            raise RuntimeError("ASR websocket not connected")

        async for msg in self.conn:
            if msg.type == aiohttp.WSMsgType.BINARY:
                response = parse_response(msg.data)
                if on_result is not None:
                    on_result(response)
                yield response
                if response.code != 0 or response.is_last_package:
                    break
            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                break
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break
