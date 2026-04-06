# Tracking Benchmark Log 2026-04-06

## Setup

Pipeline:

- `rebind_fsm`
- tracker fps: `8`
- recovery trigger: `rebind_after_missed_frames = 1`
- bound review cadence:
  - first `3` stable-bound frames after a bind/rebind: review every frame
  - after that: review every `5` stable-bound frames
- logic fixes enabled:
  - no `excluded_track_ids` filtering in recovery
  - no historical ID dependency in `track`
  - front/back reference crops are used in `track`
  - proactive front/back anchor accumulation during stable binding
  - bound-state review before allowing continued blind tracking
  - rewrite gating to avoid rewriting memory when the current binding is not review-confirmed

Model config used for the benchmark unless stated otherwise:

- `DASHSCOPE_MAIN_MODEL=qwen3.5-flash`
- `DASHSCOPE_SUB_MODEL=qwen3.5-flash`

## Completed Results

| Sequence | Evaluated Frames | Success Frames | Success Rate |
| --- | ---: | ---: | ---: |
| corridor1 | 295 | 100 | 33.90% |
| corridor2 | 1021 | 638 | 62.49% |
| lab_corridor | 1217 | 1100 | 90.39% |
| room | 151 | 132 | 87.42% |

Room result file:

- `.runtime/benchmark_room_rebind_fsm_boundreview.json`

Corridor1 result file:

- `.runtime/benchmark_corridor1_rebind_fsm_boundreview.json`

Corridor2 result file:

- `.runtime/benchmark_corridor2_rebind_fsm_boundreview.json`

Lab-corridor result file:

- `.runtime/benchmark_labcorridor_rebind_fsm_boundreview.json`

## Notes

- This result is substantially better than the earlier `63.58%` and `43.05%` runs.
- The main gain came from fixing bound-state review and rewrite gating, not from changing the model tier.
- `qwen3.5-plus` was tested separately and did not improve the room score over the same repaired logic.

## Pending

- none
