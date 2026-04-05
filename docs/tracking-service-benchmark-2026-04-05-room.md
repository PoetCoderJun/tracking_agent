# Tracking Service Benchmark 2026-04-05: room

## Goal

Run the real tracking service path, not a simplified approximation:

- `scripts.run_tracking_perception.py`
- `backend.tracking.service`
- `backend.tracking.loop`
- real Pi init chat
- real recovery behavior with `wait` / `track` / `tracking_bound`

## Setup

- Sequence: `backend/tests/dataset/room`
- Session: `svc_room_real_001`
- Device: `cpu`
- Tracker: `bytetrack.yaml`
- Observation cadence: `1.0s`
- Init text: `开始跟踪 ID 为 1 的人。`

Perception was started with a pause after the first event so service could initialize on the first observation before the rest of the stream continued.

## What Happened

1. The real service init chat succeeded on `frame_000000`.
2. The target was initially bound as `target_id = 1`.
3. The loop stayed `tracking_bound` through `frame_000008`.
4. Recovery then triggered multiple real `track` turns after the old ID disappeared from the current candidates.
5. Two recovery attempts returned `wait`.
6. A later recovery turn rebound the target from `ID 1` to `ID 4` at `frame_000015`.
7. The stream later stayed bound on `ID 4`, but the final few frames drifted badly in image space.

## Quantitative Result

This run was evaluated over the 27 emitted service observations.

- Evaluated observations: `27`
- Observations where the current active target ID existed in the emitted detections: `18`
- Successful observations under the paper-style `center distance < 50px` rule: `14`
- Success rate: `51.85%`

## Rebinding Timeline

- `frame_000000`: init binds `ID 1`
- `frame_000009`: `track` returns `wait`
- `frame_000012`: `track` returns `wait`
- `frame_000015`: `track` successfully rebinds to `ID 4`
- `frame_000020`: `track` returns `wait`

## Interpretation

This is the first real-service measurement of the current strategy.

- It is materially better than the earlier simplified stack approximation.
- The service does perform actual ID-switch rebinding in the real chain.
- The current bottlenecks are:
  - long gaps where the previous ID is gone and recovery only returns `wait`
  - late-stage drift after rebinding, where the rebound ID remains present but no longer matches the target box well

## Files

- Session state: `.runtime/service-room-real/state/sessions/svc_room_real_001/session.json`
- Perception log: `.runtime/service-room-real/perception/events.jsonl`
- Service artifacts: `.runtime/service-room-real/artifacts/`
