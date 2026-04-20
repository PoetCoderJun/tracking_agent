from __future__ import annotations

import asyncio
import sys
import types

import pytest

sys.modules.setdefault("onnxruntime", types.ModuleType("onnxruntime"))

from stt.streaming_asr import StreamingAsrClient


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def ws_connect(self, url, headers):
        raise RuntimeError("dns failed")

    async def close(self) -> None:
        self.closed = True


def test_connect_and_init_closes_session_when_ws_connect_fails(monkeypatch) -> None:
    fake_session = _FakeSession()
    monkeypatch.setattr("stt.streaming_asr.aiohttp.ClientSession", lambda: fake_session)
    monkeypatch.setattr(
        "stt.streaming_asr.asr_settings",
        lambda: {
            "ws_url": "wss://example.invalid/ws",
            "app_key": "app",
            "access_key": "access",
        },
    )

    client = StreamingAsrClient()

    async def _run() -> None:
        with pytest.raises(RuntimeError, match="dns failed"):
            await client.connect_and_init()

    asyncio.run(_run())

    assert fake_session.closed is True
    assert client.session is None
    assert client.conn is None
