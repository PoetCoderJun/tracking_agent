# Tracking Rebind Strategy 2026-04-05

## Current Strategy

The current project strategy treats recovery as a conservative ID-switch rebinding process.

Core rules:

1. `track` is not called while the current `latest_target_id` is still present in the newest observation.
2. Recovery starts only after the current target ID is absent from the newest observation.
3. Recovery is rate-limited by the loop and only retried on a newer `frame_id`.
4. During recovery, the system is conservative by default:
   - keep the current identity unless multiple visible identity cues support rebinding
   - if evidence is weak, return `wait` instead of switching
5. Explicit ID requests such as `ID 1` can force a direct target choice during `init` or `track`.

## Service / Loop Semantics

- Real service path:
  - perception writes observations
  - `capabilities.tracking.service` waits for the first frame
  - service sends one tracking init chat turn if `--init-text` is provided
  - service then launches `capabilities.tracking.loop`

- Loop behavior:
  - if there is no active target, status is `idle`
  - if the active target ID is still found in the latest observation, status is `tracking_bound`
  - only when the active target ID is missing does the loop call `process_tracking_request_direct(...)`
  - recovery calls are gated by `recovery_interval_seconds` and by new-frame arrival

## Practical Consequence

This strategy is intentionally designed for cautious rebinding after ID switch. It is not a proactive per-frame re-identification policy.

That means:

- false positive rebinding risk is reduced
- missed recovery can increase if the old track ID persists on the wrong person
- performance can be lower than a denser perception-only benchmark because the real stack:
  - sees fewer frames
  - only triggers `track` after a miss
  - may choose `wait` instead of rebinding

## What Must Be Measured

Any serious benchmark of this strategy should use the real service semantics:

- perception cadence from `scripts/run_tracking_perception.py`
- init through `capabilities.tracking.service`
- recovery through `capabilities.tracking.loop`
- the actual `wait` / `track` / `tracking_bound` behavior, not a simplified approximation
