from __future__ import annotations

import asyncio
import sys
import time
import types

from agent.voice_input import VoiceInputBridge


def test_voice_input_bridge_reads_text_from_stt_backend(monkeypatch) -> None:
    captured: list[str] = []

    class _FakeAsrVadClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.result_queue: asyncio.Queue[str] = asyncio.Queue()

        async def start(self) -> None:
            await self.result_queue.put("voice from stt")

        async def stop(self) -> None:
            return None

    fake_module = types.ModuleType("stt")
    fake_module.AsrVadClient = _FakeAsrVadClient
    monkeypatch.setitem(sys.modules, "stt", fake_module)

    bridge = VoiceInputBridge(on_text=captured.append)
    try:
        bridge.start()
        deadline = time.time() + 1.0
        while not captured and time.time() < deadline:
            time.sleep(0.01)
    finally:
        bridge.stop()

    assert captured == ["voice from stt"]
