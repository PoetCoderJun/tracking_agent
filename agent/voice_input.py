from __future__ import annotations

import asyncio
import logging
import threading
from typing import Callable, Optional


logger = logging.getLogger(__name__)


class VoiceInputBridge:
    def __init__(
        self,
        *,
        input_device: str | int | None = None,
        rate: int = 16000,
        channels: int = 1,
        frame_ms: int = 32,
        on_text: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._input_device = input_device
        self._rate = int(rate)
        self._channels = int(channels)
        self._frame_ms = int(frame_ms)
        self._on_text = on_text
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = threading.Event()
        self._error: BaseException | None = None

    @property
    def error(self) -> BaseException | None:
        return self._error

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._error = None
        self._thread = threading.Thread(target=self._thread_main, name="VoiceInputBridge", daemon=True)
        self._thread.start()
        self._running.wait(timeout=5.0)
        if self._error is not None:
            raise RuntimeError(f"voice input startup failed: {self._error}") from self._error

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._async_main())
        except BaseException as exc:
            self._error = exc
            logger.exception("Voice input bridge failed: %s", exc)
            self._running.set()

    async def _async_main(self) -> None:
        try:
            from stt import AsrVadClient
        except ModuleNotFoundError as exc:
            if exc.name in {"pyaudio", "onnxruntime"}:
                raise RuntimeError(
                    "Voice input dependencies are not installed in the project environment. Run `uv sync` first."
                ) from exc
            raise

        client = AsrVadClient(
            input_device=self._input_device,
            rate=self._rate,
            channels=self._channels,
            frame_ms=self._frame_ms,
        )
        try:
            await client.start()
            self._running.set()
            while not self._stop_event.is_set():
                try:
                    text = await asyncio.wait_for(client.result_queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                cleaned = str(text or "").strip()
                if cleaned and self._on_text is not None:
                    self._on_text(cleaned)
        finally:
            await client.stop()
