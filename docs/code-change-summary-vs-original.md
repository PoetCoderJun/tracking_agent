# Code Change Summary Vs Original Snapshot

This document compares the current workspace against the copied original snapshot at:

`embodied_harness-main/`

The goal of the changes was to let `uv run e-agent --voice-input` accept streaming speech, convert it to text, and feed that text into the existing `pi` TUI with minimal disruption to the original runtime path.

## New Files

These files do not exist in the copied original snapshot and were added in the current workspace.

- `agent/voice_input.py`
  - Adds a small bridge that starts the STT client in a background thread and forwards finalized text to a callback.
  - This is the runtime entry point for voice input on the Python side.

- `agent/windows_console_input.py`
  - Adds a Windows-specific console input injector using `WriteConsoleInputW`.
  - This is what makes recognized text behave like a user typed it directly into the current `pi` chat box and pressed Enter.

- `stt/__init__.py`
- `stt/audio_sampler.py`
- `stt/runtime_config.py`
- `stt/streaming_asr.py`
- `stt/utils.py`
- `stt/vad_asr_client.py`
  - These files form the local STT stack now used by `e-agent --voice-input`.
  - The stack is structured as:
    - microphone capture
    - ONNX VAD segmentation
    - streaming ASR websocket client
    - result queue back into `agent/voice_input.py`

- `models/silvervad.onnx`
  - Adds the ONNX VAD model file used by the current STT pipeline.

- `tests/test_voice_input.py`
  - Adds a unit test for the voice bridge.

- `tests/test_streaming_asr.py`
  - Adds a unit test for ASR websocket connection cleanup on failure.

- `tests/test_perception_recorder.py`
  - Adds a unit test for concurrent keyframe deletion tolerance.

## Modified Existing Files

These files exist in both the original snapshot and the current workspace, but their behavior has changed.

- `agent/e_agent.py`
  - Added Windows-aware `pi` executable resolution.
    - The original version assumed `pi` directly.
    - The current version resolves `pi.cmd` / `pi.exe` / `pi` on Windows.
  - Added voice-input CLI flags:
    - `--voice-input`
    - `--voice-device`
    - `--voice-rate`
    - `--voice-frame-ms`
  - Added `pi` session directory handling so voice follow-up can reuse the active `pi` session.
  - Added `_VoiceTurnDispatcher` to route recognized text into the active conversation.
  - On Windows, voice text is now injected into the currently running TUI instead of spawning a separate visible interaction path.
  - The supervision loop now starts and stops the voice bridge alongside the normal `pi` process.

- `world/perception/recorder.py`
  - The original `saved_frame_paths()` assumed all files listed during directory iteration would still exist when `stat()` was called.
  - The current version tolerates `FileNotFoundError` during scan and skips vanished files.
  - This avoids runtime crashes when keyframes are removed concurrently while tracking/runtime code is reading the folder.

- `pyproject.toml`
  - Added runtime dependencies needed by the speech path:
    - `aiohttp`
    - `onnxruntime`
    - `PyAudio`
  - Expanded package discovery to include `stt*`.
  - The original snapshot only packaged:
    - `agent*`
    - `world*`
    - `capabilities*`
    - `interfaces*`
    - `skills*`

- `requirements.txt`
  - Added the same speech-related dependencies required by the current local STT implementation:
    - `aiohttp`
    - `onnxruntime`
    - `PyAudio`

- `tests/test_pi_agent_runner.py`
  - Extended to cover the new Windows and voice-input behavior.
  - Compared with the original snapshot, the current version adds tests for:
    - Windows launcher resolution preferring `pi.cmd`
    - voice text dispatch into the `pi` session
    - session directory expectations used by the new follow-up flow

## Behavior Changes Inside New STT Stack

These are not "modified files" relative to the original snapshot because the original snapshot had no `stt/` package, but they are important current behaviors.

- `stt/runtime_config.py`
  - Centralizes STT-related environment loading from `.ENV`.
  - Supports both current tracking-prefixed variable names and legacy pointing-prefixed names.

- `stt/streaming_asr.py`
  - Implements the websocket protocol used to stream PCM audio to the ASR service.
  - Includes explicit cleanup when websocket initialization fails, so failed connects do not leave an unclosed client session behind.

- `stt/vad_asr_client.py`
  - Implements speech start/end detection with ONNX VAD plus simple dB gating.
  - Streams completed speech segments to ASR and publishes final text into `result_queue`.
  - Includes a failure path where STT connect failure drops the current speech segment instead of crashing the entire bridge.

## What Did Not Exist In The Original Snapshot

The copied original snapshot does not contain these parts at all:

- `agent/voice_input.py`
- `agent/windows_console_input.py`
- the entire `stt/` package
- `models/silvervad.onnx`
- the 3 new test files listed above

That means the original snapshot had no direct speech-to-text input path into `e-agent`.

## Practical Summary

Relative to the copied original snapshot, the current codebase adds one new capability and two supporting hardening changes.

- New capability:
  - `e-agent` can accept streaming voice input and turn it into normal `pi` chat turns.

- Platform adaptation:
  - Windows `pi.cmd` launcher resolution and Windows console text injection.

- Stability hardening:
  - ASR connection failure cleanup.
  - keyframe scan tolerance when files disappear during runtime.

## Notes

- This summary is intentionally based on the copied original snapshot under `embodied_harness-main/`, not on earlier intermediate states of this workspace.
- Local runtime artifacts such as `.pytest_cache/`, `pytest-of-35357/`, `.runtime/`, and `robot_agent_runtime.egg-info/` are not treated as code changes here.
