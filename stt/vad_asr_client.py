from __future__ import annotations

import asyncio
import logging
import math
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional, Union

import numpy as np
import onnxruntime as ort

from .audio_sampler import AudioSampler
from .runtime_config import vad_model_path
from .streaming_asr import AsrResponse, StreamingAsrClient


logger = logging.getLogger(__name__)

RATE = 16000
CHANNELS = 1
FRAME_MS = 32
BYTES_PER_SAMPLE = 2
FRAMES_PER_CHUNK = 6
BYTES_PER_FRAME = int(RATE * (FRAME_MS / 1000.0) * CHANNELS * BYTES_PER_SAMPLE)
BYTES_PER_CHUNK = BYTES_PER_FRAME * FRAMES_PER_CHUNK
PCM_REF = 32768.0

DB_SMOOTH_ALPHA = 0.15
DB_GATE_DBFS = -40.0
DB_END_DBFS = -45.0
P_START = 0.40
P_END = 0.25
START_FRAMES = 3
END_FRAMES = 8
PREROLL_MS = 480

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VAD_MODEL_PATH = REPO_ROOT / "models" / "silvervad.onnx"

DeviceSpec = Union[int, str, None]
_vad_runtime = None


class OnnxVadRuntime:
    def __init__(self, model_path: Path = DEFAULT_VAD_MODEL_PATH):
        resolved_path = vad_model_path(model_path)
        if not resolved_path.is_file():
            raise FileNotFoundError(f"VAD model not found: {resolved_path}")

        session_options = ort.SessionOptions()
        session_options.intra_op_num_threads = 1
        session_options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(resolved_path),
            sess_options=session_options,
            providers=["CPUExecutionProvider"],
        )

        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if len(inputs) < 3 or len(outputs) < 2:
            raise RuntimeError(
                "Unexpected silvervad.onnx signature: "
                f"{len(inputs)} inputs, {len(outputs)} outputs."
            )

        self.model_path = resolved_path
        self.input_name = inputs[0].name
        self.state_name = inputs[1].name
        self.sample_rate_name = inputs[2].name
        self.output_name = outputs[0].name
        self.output_state_name = outputs[1].name


class OnnxVadStream:
    def __init__(self, runtime: OnnxVadRuntime):
        self.runtime = runtime
        self.reset()

    def reset(self) -> None:
        self.state = np.zeros((2, 1, 128), dtype=np.float32)

    def infer_frame(self, frame: bytes, rate: int) -> float:
        pcm_int16 = np.frombuffer(frame, dtype=np.int16)
        if pcm_int16.size == 0:
            return 0.0

        wav_float32 = (pcm_int16.astype(np.float32) / PCM_REF).reshape(1, -1)
        prob, next_state = self.runtime.session.run(
            [self.runtime.output_name, self.runtime.output_state_name],
            {
                self.runtime.input_name: wav_float32,
                self.runtime.state_name: self.state,
                self.runtime.sample_rate_name: np.array(rate, dtype=np.int64),
            },
        )
        self.state = np.asarray(next_state, dtype=np.float32)
        return float(np.asarray(prob).reshape(-1)[0])


def load_vad_runtime() -> OnnxVadRuntime:
    global _vad_runtime
    if _vad_runtime is None:
        _vad_runtime = OnnxVadRuntime()
        logger.info("[VAD] silvervad ONNX loaded from %s", _vad_runtime.model_path)
    return _vad_runtime


def vad_prob_from_frame(frame: bytes, rate: int) -> float:
    runtime = load_vad_runtime()
    stream = OnnxVadStream(runtime)
    return stream.infer_frame(frame, rate)


def vad_prob_from_frame_with_stream(
    frame: bytes,
    rate: int,
    vad_stream: Optional[OnnxVadStream],
) -> float:
    if vad_stream is None:
        return 0.0
    return vad_stream.infer_frame(frame, rate)


def frame_dbfs_int16(frame: bytes) -> float:
    if not frame:
        return -120.0
    data = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    if data.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(data * data)))
    if rms < 1e-8:
        return -120.0
    return 20.0 * math.log10(rms / PCM_REF)


class AsrVadClient:
    def __init__(
        self,
        input_device: DeviceSpec = None,
        rate: int = RATE,
        channels: int = CHANNELS,
        frame_ms: int = FRAME_MS,
        on_speech_start: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        self.input_device = input_device
        self.rate = rate
        self.channels = channels
        self.frame_ms = frame_ms
        self.on_speech_start = on_speech_start
        self.sampler: Optional[AudioSampler] = None
        self.vad_state = "silence"
        self.speech_run = 0
        self.silence_run = 0
        self.speech_frames_in_segment = 0
        self.current_asr: Optional[StreamingAsrClient] = None
        self.current_recv_task: Optional[asyncio.Task] = None
        self.chunk_buf = bytearray()
        self._last_stream_text = ""
        self.result_queue: asyncio.Queue[str] = asyncio.Queue()
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._vad_stream: Optional[OnnxVadStream] = None
        self._preroll_buf = bytearray()
        self._preroll_max_bytes = int(self.rate * 2 * (PREROLL_MS / 1000.0))
        self._speech_start_ts: Optional[float] = None
        self._speech_end_ts: Optional[float] = None
        self._asr_final_ts: Optional[float] = None
        self._queue_put_ts: Optional[float] = None

    async def start(self):
        load_vad_runtime()
        self._vad_stream = OnnxVadStream(load_vad_runtime())
        self.sampler = AudioSampler(
            input_device=self.input_device,
            rate=self.rate,
            channels=self.channels,
            frame_ms=self.frame_ms,
            queue_max_frames=200,
            verbose=True,
        )
        self.sampler.start()
        self._running = True
        loop = asyncio.get_running_loop()
        self._loop_task = loop.create_task(self._main_loop(), name="AsrVadMainLoop")
        logger.info("[ASR-VAD] main loop started")

    async def stop(self):
        self._running = False
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

        if self.current_recv_task is not None:
            self.current_recv_task.cancel()
        if self.current_asr is not None:
            try:
                await self.current_asr.close()
            except Exception:
                pass
            self.current_asr = None

        if self.sampler is not None and self.sampler.running:
            self.sampler.stop()
        self._vad_stream = None
        logger.info("[ASR-VAD] stopped")

    async def _graceful_finish_current_asr(self, wait_timeout: float = 10.0):
        recv_task = self.current_recv_task
        asr = self.current_asr
        self.current_recv_task = None
        self.current_asr = None

        if recv_task is not None:
            try:
                await asyncio.wait_for(recv_task, timeout=wait_timeout)
            except Exception:
                recv_task.cancel()
                try:
                    await recv_task
                except Exception:
                    pass

        if asr is not None:
            try:
                await asr.close()
            except Exception:
                pass

        self.chunk_buf.clear()
        self._last_stream_text = ""

    async def _main_loop(self):
        assert self.sampler is not None
        loop = asyncio.get_running_loop()
        self._dbfs_ema = None
        min_seg_seconds = 0.50
        min_seg_frames = max(1, int(min_seg_seconds / (self.frame_ms / 1000.0)))

        try:
            while self._running:
                frame = await loop.run_in_executor(None, self.sampler.queue.get)
                frame = bytes(frame)
                self._preroll_buf.extend(frame)
                if len(self._preroll_buf) > self._preroll_max_bytes:
                    self._preroll_buf = self._preroll_buf[-self._preroll_max_bytes :]

                db = frame_dbfs_int16(frame)
                if self._dbfs_ema is None:
                    self._dbfs_ema = db
                else:
                    self._dbfs_ema = DB_SMOOTH_ALPHA * db + (1 - DB_SMOOTH_ALPHA) * self._dbfs_ema
                db_s = float(self._dbfs_ema)
                prob = vad_prob_from_frame_with_stream(frame, self.rate, self._vad_stream)
                db_gate_ok = db_s >= DB_GATE_DBFS
                if self.vad_state == "silence":
                    if db_gate_ok and prob >= P_START:
                        self.speech_run += 1
                        if self.speech_run >= START_FRAMES:
                            self.vad_state = "speech"
                            self.speech_run = 0
                            self.silence_run = 0
                            self.chunk_buf.clear()
                            self.speech_frames_in_segment = 0
                            self._speech_start_ts = time.perf_counter()
                            self._speech_end_ts = None
                            self._asr_final_ts = None
                            self._queue_put_ts = None
                            print(">>> Speech START", flush=True)
                            if self.on_speech_start is not None:
                                await self.on_speech_start()
                            self.current_asr = StreamingAsrClient()
                            try:
                                await self.current_asr.connect_and_init()
                            except Exception:
                                logger.exception("[ASR-VAD] failed to connect streaming ASR")
                                print(">>> Speech DROPPED (STT connect failed)", flush=True)
                                self.vad_state = "silence"
                                await self._graceful_finish_current_asr(wait_timeout=0.1)
                                continue
                            preroll = bytes(self._preroll_buf)
                            self._preroll_buf.clear()
                            if preroll:
                                self.chunk_buf.extend(preroll)
                                while len(self.chunk_buf) >= BYTES_PER_CHUNK and self.current_asr is not None:
                                    chunk = bytes(self.chunk_buf[:BYTES_PER_CHUNK])
                                    del self.chunk_buf[:BYTES_PER_CHUNK]
                                    await self.current_asr.send_audio_chunk(chunk, is_last=False)

                            async def recv_task_fn(asr_client: StreamingAsrClient):
                                async for _ in asr_client.recv_loop(on_result=self._handle_asr_result):
                                    pass

                            self.current_recv_task = asyncio.create_task(recv_task_fn(self.current_asr))
                    else:
                        self.speech_run = 0
                else:
                    self.speech_frames_in_segment += 1
                    allow_end = self.speech_frames_in_segment >= min_seg_frames
                    end_candidate = db_s <= DB_END_DBFS or prob <= P_END
                    if allow_end and end_candidate:
                        self.silence_run += 1
                        if self.silence_run >= END_FRAMES:
                            self.vad_state = "silence"
                            self.speech_run = 0
                            self.silence_run = 0
                            self._speech_end_ts = time.perf_counter()
                            print(">>> Speech END", flush=True)
                            if self.current_asr is not None:
                                tail = bytes(self.chunk_buf)
                                self.chunk_buf.clear()
                                await self.current_asr.send_audio_chunk(tail, is_last=True)
                                if self.current_recv_task is not None:
                                    try:
                                        await asyncio.wait_for(self.current_recv_task, timeout=5.0)
                                    except asyncio.TimeoutError:
                                        logger.warning("[ASR-VAD] recv task not finished in 5s after final chunk")
                                    except Exception:
                                        logger.exception("[ASR-VAD] recv task failed after final chunk")
                                await self._graceful_finish_current_asr()
                            continue
                    else:
                        self.silence_run = 0

                if self.vad_state == "speech":
                    self.chunk_buf.extend(frame)
                    while len(self.chunk_buf) >= BYTES_PER_CHUNK:
                        chunk = bytes(self.chunk_buf[:BYTES_PER_CHUNK])
                        self.chunk_buf = bytearray(self.chunk_buf[BYTES_PER_CHUNK :])
                        if self.current_asr is not None:
                            await self.current_asr.send_audio_chunk(chunk, is_last=False)
        except asyncio.CancelledError:
            logger.info("[ASR-VAD] main loop cancelled")
        finally:
            logger.info("[ASR-VAD] main loop finished")

    def _on_stream_delta(self, delta_text: str, is_final: bool):
        if is_final:
            full_sentence = self._last_stream_text
            if full_sentence.strip():
                self._queue_put_ts = time.perf_counter()
                if self._speech_start_ts is not None:
                    total_ms = (self._queue_put_ts - self._speech_start_ts) * 1000.0
                    if self._speech_end_ts is not None:
                        end_to_queue_ms = (self._queue_put_ts - self._speech_end_ts) * 1000.0
                    else:
                        end_to_queue_ms = -1.0
                    if self._asr_final_ts is not None:
                        final_to_queue_ms = (self._queue_put_ts - self._asr_final_ts) * 1000.0
                    else:
                        final_to_queue_ms = -1.0
                    print(
                        "[STT TIMING] "
                        f"start_to_queue={total_ms:.1f}ms "
                        f"end_to_queue={end_to_queue_ms:.1f}ms "
                        f"final_to_queue={final_to_queue_ms:.1f}ms",
                        flush=True,
                    )
                asyncio.create_task(self.result_queue.put(full_sentence))

    def _handle_asr_result(self, resp: AsrResponse):
        if resp.code != 0:
            logger.warning("[ASR] error code=%s payload=%r", resp.code, resp.payload_msg)
            return

        payload = resp.payload_msg or {}
        result = payload.get("result") or {}
        text = result.get("text") or ""
        utterances = result.get("utterances") or []
        utt_text = ""
        definite = False
        if utterances:
            last_utt = utterances[-1]
            utt_text = last_utt.get("text") or ""
            definite = bool(last_utt.get("definite", False))

        current_text = utt_text or text
        if not current_text:
            return

        old = self._last_stream_text
        new = current_text
        prefix_len = 0
        max_len = min(len(old), len(new))
        while prefix_len < max_len and old[prefix_len] == new[prefix_len]:
            prefix_len += 1

        delta = new[prefix_len:]
        self._last_stream_text = new
        is_final = resp.is_last_package or definite
        if not delta.strip() and not is_final:
            return

        self._on_stream_delta(delta, is_final)
        if is_final:
            self._asr_final_ts = time.perf_counter()
            if self._speech_end_ts is not None:
                end_to_final_ms = (self._asr_final_ts - self._speech_end_ts) * 1000.0
                print(
                    f"[STT TIMING] end_to_asr_final={end_to_final_ms:.1f}ms",
                    flush=True,
                )
            logger.info("[ASR][FINAL] %s", current_text)
            self._last_stream_text = ""
