# Tracking No-Reason Benchmark 2026-04-11

## Setup

- tracking select model: `qwen3.5-flash`
- tracking select output: no `reason`
- internal rewrite input: no `confirmation_reason`
- memory schema: unchanged
- rewrite path: async/background writeback
- pipeline: `rebind_fsm`
- tracker fps: `8.0`
- observation interval: `1.0s`
- recovery trigger: `rebind_after_missed_frames = 1`

## Benchmark Results

| Sequence | Previous Flash Baseline | No-Reason | Delta |
| --- | ---: | ---: | ---: |
| corridor1 | 75.68% | 78.38% | +2.70 |
| corridor2 | 74.62% | 93.85% | +19.23 |
| lab_corridor | 93.55% | 94.19% | +0.64 |
| room | 100.00% | 100.00% | +0.00 |

## Result Files

- `corridor1`: `.runtime/benchmark_corridor1_qwen35flash_no_reason_rebind_fsm_2026-04-11.json`
- `corridor2`: `.runtime/benchmark_corridor2_qwen35flash_no_reason_rebind_fsm_2026-04-11.json`
- `lab_corridor`: `.runtime/benchmark_labcorridor_qwen35flash_no_reason_rebind_fsm_2026-04-11.json`
- `room`: `.runtime/benchmark_room_qwen35flash_no_reason_rebind_fsm_2026-04-11.json`

## Turn-Time Approximation From Full Benchmarks

Using benchmark wall time divided by triggered tracking turns:

| Sequence | Benchmark Duration | Triggered Turns | Approx Avg Seconds / Turn |
| --- | ---: | ---: | ---: |
| corridor1 | 180.01s | 49 | 3.67s |
| corridor2 | 553.18s | 148 | 3.74s |
| lab_corridor | 599.19s | 176 | 3.40s |
| room | 94.10s | 27 | 3.49s |

Triggered turn counts:

- `corridor1`: `46` review turns, `3` rebind turns
- `corridor2`: `134` review turns, `14` rebind turns
- `lab_corridor`: `147` review turns, `29` rebind turns
- `room`: `20` review turns, `7` rebind turns

## 3s Loop Assessment

### What the benchmark timing means

These `3.40s` to `3.74s` numbers are not just LLM latency. They also include:

- benchmark-side video iteration
- YOLO + ByteTrack processing in the same run
- runtime state I/O
- tracking select calls
- background rewrite work occurring between turns

### Hot-path conclusion

From the single-turn no-reason experiment, the `track select` hot path was around:

- `2.677s` average on `corridor2`

That is below `3s`.

### Practical conclusion

`3s` is now plausible for a stable loop if:

- perception/system1 is already running separately
- tracking turn only consumes the latest snapshot
- rewrite remains asynchronous

But it is still a tight budget, not a wide-margin one.

In other words:

- for the main `select` decision path, `3s` is now basically workable
- for full end-to-end benchmark runtime, average turn cost still lands slightly above `3s`
- so a `3s` loop should work in the real split-runtime architecture, but you should expect little slack under network variance

## Bottom Line

- Removing `reason` did **not** reduce benchmark accuracy on the four tested sequences.
- On these four runs it actually improved or preserved every sequence.
- Async rewrite remains compatible with the no-reason setup.
- `3s` is now close to workable for the main loop, but remains a near-boundary operating point rather than a very conservative one.
