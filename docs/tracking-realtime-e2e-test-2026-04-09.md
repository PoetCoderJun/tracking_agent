# Tracking Realtime E2E Test 2026-04-09

## Goal

Record and execute a realistic end-to-end tracking test that preserves the real-world timing model:

1. Use `robot-agent-environment-writer` to write the first frame.
2. Keep the first frame stable while the main Agent initializes the target.
3. Only after init should continuous environment writing resume, to simulate:
   - the observed person is mostly static during initialization
   - once the dog starts following, the person keeps moving ahead
4. For video sources, playback progress must stay aligned with wall time. If PI cannot keep up, that is treated as a real latency limitation rather than something to hide with older frames.

## Test Fixture

- Video: `/Users/huzujun/Desktop/new/tracking_agent/tests/fixtures/demo_video.mp4`
- Pause sentinel: `/Users/huzujun/Desktop/new/tracking_agent/.runtime/test-pause.flag`

## Planned Procedure

1. Clear runtime state and any lingering `robot-agent-environment-writer` / `e-agent` / `pi` processes.
2. Start `robot-agent-environment-writer` with:
   - `--source tests/fixtures/demo_video.mp4`
   - `--realtime-playback`
   - `--pause-after-first-event-file ./.runtime/test-pause.flag`
3. Wait for:
   - `perception/snapshot.json` latest frame to become `frame_000000`
   - `system1/snapshot.json` latest result to be available for the same frame
4. Start the main Agent flow with:
   - `uv run e-agent --fresh -- "请跟踪穿黑衣服的人"`
5. Observe whether:
   - PI directly enters `tracking-init`
   - session state is updated
   - init succeeds or asks a clarification question
6. If init succeeds, remove the pause sentinel and continue realtime writing.
7. If init fails, record the blocker exactly as observed.

## Commands Used

```bash
pkill -f 'robot-agent-environment-writer' || true
pkill -f 'uv run e-agent' || true
pkill -f 'pi - tracking_agent' || true
rm -rf .runtime/agent-runtime/sessions .runtime/agent-runtime/perception .runtime/agent-runtime/system1 .runtime/agent-runtime/active_session.json
mkdir -p .runtime/agent-runtime

rm -f .runtime/test-pause.flag
touch .runtime/test-pause.flag
set -a && source .ENV && set +a && \
  uv run robot-agent-environment-writer \
    --source tests/fixtures/demo_video.mp4 \
    --realtime-playback \
    --pause-after-first-event-file ./.runtime/test-pause.flag

set -a && source .ENV && set +a && \
  uv run e-agent --fresh -- "请跟踪穿黑衣服的人"

uv run robot-agent session-show --state-root ./.runtime/agent-runtime
```

## Observations

### Phase 1: First Frame Written And Paused

Writer successfully reached the expected pause point after the first emitted event.

Observed writer output:

```text
视觉感知：frame_id=frame_000000, ...
yolo+bytetrack：frame_id=frame_000000, detection_count=1, track_ids=[1]
```

Persisted snapshots at the pause point:

- Perception latest frame: `frame_000000`
- System1 latest frame result: `frame_000000`
- System1 detections: one person candidate, `track_id = 1`

This means the intended init condition was successfully created:

- the first frame was stable
- system1 had already produced candidate boxes
- the world had not yet resumed moving forward

### Phase 2: Main Agent Init Attempt

The PI-side routing did improve enough to hit the tracking path:

- session `runner_state.turn_kind` became `pi:tracking-init`
- the user message was persisted as `跟踪穿黑衣服的人`
- the turn produced a processed `init` result rather than staying in pure code-analysis mode

However, the init did **not** succeed.

Persisted result:

```json
{
  "behavior": "init",
  "frame_id": "frame_000000",
  "target_id": null,
  "found": false,
  "decision": "ask",
  "text": "当前画面中没有检测到任何候选框，无法进行跟踪。",
  "clarification_question": "请提供包含目标人物的候选框数据，或者确认是否需要在下一帧重新检测目标？"
}
```

## Current Blocker

At the paused first-frame moment:

- `system1/snapshot.json` clearly contained one candidate box for `frame_000000`
- but `tracking-init` still concluded that the current frame had **no candidate boxes**

This indicates the current init path is not consuming the same candidate source that the paused realtime environment writer already produced.

The likely failure surface is:

- `tracking-init` falls back to perception-side recent frames that do not carry system1 detections
- instead of using the current system1 candidate result for the same wall-time frame

So the present blocker is **not** “PI failed to trigger the skill”.
The blocker is: **the init backend path cannot see the already-written system1 candidate set at the paused first frame**.

## Interpretation

This test now more faithfully simulates the real-world flow:

- video playback is tied to wall time
- the first frame is held steady during initialization
- if PI is slow, that is treated as real latency

Under that setup, the exposed failure is a backend context-assembly mismatch between:

- the paused first frame’s system1 result
- and what `tracking-init` actually reads as its candidate set

## Most Concrete Next Step

Fix the tracking init context so that, during initialization, the current candidate set is sourced from the already-written system1 result for the same current frame, instead of concluding “no candidate boxes” while `system1/snapshot.json` already has detections.

## Follow-up Result After Fix

After switching the tracking selection path to use environment/perception + same-frame system1 as the candidate source of truth, the same paused-first-frame flow was re-run.

Observed result:

- `frame_000000` stayed paused with `system1` candidate `track_id = 1`
- the PI-side `tracking-init` completed successfully
- the session persisted:
  - `latest_result.behavior = "init"`
  - `latest_result.frame_id = "frame_000000"`
  - `latest_result.target_id = 1`
  - `latest_result.found = true`
  - `latest_result.decision = "track"`
- tracking memory and reference crops were written
- the supervisor moved into `runner_state.turn_kind = "tracking"` and `skill_cache.tracking.lifecycle_status = "running"`

This confirms the original blocker is fixed:

- init no longer reports “没有候选框” when `system1` already has detections for the paused first frame
- the main flow can initialize the target from the paused first frame and start the follow-up tracking loop

## Follow-up E2E Result

The same run was continued after removing the pause sentinel so that `robot-agent-environment-writer` could resume realtime playback.

Observed follow-up state from the persisted session:

- `latest_result.behavior = "init"`
- `latest_result.frame_id = "frame_000000"`
- `latest_result.target_id = 1`
- `latest_result.found = true`
- `skill_cache.tracking.latest_target_id = 1`
- `skill_cache.tracking.lifecycle_status = "running"`
- `runner_state.turn_kind = "tracking"`
- `runner_state.turn_in_flight = true`

Interpretation:

- initialization completed successfully from the paused first frame
- after unpausing, the supervisor immediately entered the follow-up tracking lane
- the session stayed bound to `target_id = 1` and did not fall back to “no candidates”, clarification, or idle state at the handoff point

This is sufficient to say the paused-first-frame follow-up flow has started correctly.
The next incremental check would be a longer observation window to confirm:

- `frame_id` keeps advancing after unpause
- `latest_target_id` stays stable while the target remains visible
- `lifecycle_status` stays in `running` / `bound` rather than falling into clarification or stop states
