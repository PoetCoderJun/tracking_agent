from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np
import pyaudio

from .utils import DropOldestQueue, PyAudioManager, find_device_index


class AudioSampler:
    def __init__(
        self,
        input_device: Optional[str] = None,
        rate: int = 16000,
        channels: int = 1,
        frame_ms: int = 32,
        sample_format: int = pyaudio.paInt16,
        queue_max_frames: int = 200,
        exception_on_overflow: bool = False,
        verbose: bool = True,
    ) -> None:
        self.rate = rate
        self.channels = channels
        self.frame_ms = frame_ms
        self.sample_format = sample_format
        self.exception_on_overflow = exception_on_overflow
        self.verbose = verbose
        self.queue = DropOldestQueue(queue_max_frames)
        self.frames_per_buffer = max(1, int(self.rate * self.frame_ms / 1000))
        self._input_device_spec = input_device
        self._pa = None
        self._stream = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._capture_rate = self.rate
        self._capture_frames_per_buffer = self.frames_per_buffer

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="AudioSampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def _resolve_capture_rate(self, pa: pyaudio.PyAudio, device_index: int) -> int:
        candidate_rates = [self.rate]
        device_info = pa.get_device_info_by_index(device_index)
        default_rate = int(round(float(device_info.get("defaultSampleRate", self.rate))))
        if default_rate not in candidate_rates:
            candidate_rates.append(default_rate)
        for fallback_rate in (48000, 44100, 32000, 16000, 8000):
            if fallback_rate not in candidate_rates:
                candidate_rates.append(fallback_rate)

        for candidate_rate in candidate_rates:
            try:
                pa.is_format_supported(
                    candidate_rate,
                    input_device=device_index,
                    input_channels=self.channels,
                    input_format=self.sample_format,
                )
                return candidate_rate
            except ValueError:
                continue

        raise OSError(f"No supported capture rate found for input device index={device_index}")

    def _resample_if_needed(self, data: bytes) -> bytes:
        if self._capture_rate == self.rate:
            return data

        pcm = np.frombuffer(data, dtype=np.int16)
        if pcm.size == 0:
            return data

        target_samples = max(1, int(round(pcm.size * self.rate / self._capture_rate)))
        src_positions = np.arange(pcm.size, dtype=np.float32)
        dst_positions = np.linspace(0, pcm.size - 1, num=target_samples, dtype=np.float32)
        resampled = np.interp(dst_positions, src_positions, pcm.astype(np.float32))
        return np.clip(np.rint(resampled), -32768, 32767).astype(np.int16).tobytes()

    def _run(self) -> None:
        pa = PyAudioManager.acquire()
        self._pa = pa
        try:
            device_index = find_device_index(pa, want_input=True, name_substr=self._input_device_spec)
            if device_index is None:
                device_index = pa.get_default_input_device_info()["index"]
            device_info = pa.get_device_info_by_index(device_index)
            device_name = device_info.get("name", str(device_index))
            self._capture_rate = self._resolve_capture_rate(pa, device_index)
            self._capture_frames_per_buffer = max(
                1, int(self._capture_rate * self.frame_ms / 1000)
            )

            if self.verbose:
                print(f"[AudioSampler] Open input device: {device_name} (index={device_index})")
                print(
                    f"[AudioSampler] capture_rate={self._capture_rate} target_rate={self.rate} "
                    f"channels={self.channels} frame={self.frame_ms}ms "
                    f"({self._capture_frames_per_buffer} capture samples/frame -> {self.frames_per_buffer} target samples/frame)"
                )

            self._stream = pa.open(
                format=self.sample_format,
                channels=self.channels,
                rate=self._capture_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self._capture_frames_per_buffer,
            )

            try:
                self._stream.read(self._capture_frames_per_buffer, exception_on_overflow=False)
            except Exception:
                pass

            while not self._stop.is_set():
                try:
                    data = self._stream.read(
                        self._capture_frames_per_buffer,
                        exception_on_overflow=self.exception_on_overflow,
                    )
                    data = self._resample_if_needed(data)
                    self.queue.put(data)
                except OSError:
                    time.sleep(0.005)
        finally:
            try:
                if self._stream is not None:
                    self._stream.stop_stream()
                    self._stream.close()
            finally:
                self._stream = None
                if self._pa is not None:
                    PyAudioManager.release()
                self._pa = None
                if self.verbose:
                    print("[AudioSampler] Stopped.")
