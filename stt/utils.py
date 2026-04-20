from __future__ import annotations

from collections import deque
import threading
import time
from typing import Deque, Optional

import pyaudio


class PyAudioManager:
    _lock = threading.Lock()
    _pa = None
    _ref = 0

    @classmethod
    def acquire(cls):
        with cls._lock:
            if cls._pa is None:
                cls._pa = pyaudio.PyAudio()
            cls._ref += 1
            return cls._pa

    @classmethod
    def release(cls):
        with cls._lock:
            cls._ref -= 1
            if cls._ref <= 0 and cls._pa is not None:
                cls._pa.terminate()
                cls._pa = None
                cls._ref = 0


class DropOldestQueue:
    def __init__(self, maxlen: int):
        if maxlen <= 0:
            raise ValueError("maxlen must be > 0")
        self._dq: Deque[bytes] = deque(maxlen=maxlen)
        self._cv = threading.Condition()

    def put(self, item: bytes) -> None:
        with self._cv:
            self._dq.append(item)
            self._cv.notify()

    def get(self, block: bool = True, timeout: Optional[float] = None) -> bytes:
        with self._cv:
            if not block:
                if not self._dq:
                    raise RuntimeError("queue empty")
                return self._dq.popleft()

            end = None if timeout is None else (time.time() + timeout)
            while not self._dq:
                remaining = None if end is None else (end - time.time())
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("queue get timed out")
                self._cv.wait(timeout=remaining)
            return self._dq.popleft()


def find_device_index(pa: pyaudio.PyAudio, want_input: bool, name_substr: Optional[str]):
    name_substr_lc = (name_substr or "").lower()
    candidates = []
    for index in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(index)
        in_ch = int(info["maxInputChannels"])
        out_ch = int(info["maxOutputChannels"])
        if want_input and in_ch == 0:
            continue
        if not want_input and out_ch == 0:
            continue
        name = str(info["name"])
        if not name_substr or name_substr_lc in name.lower():
            candidates.append((index, info))

    if not candidates:
        return None

    exact = [c for c in candidates if str(c[1]["name"]).lower() == name_substr_lc]
    if exact:
        return exact[0][0]

    return candidates[0][0]
