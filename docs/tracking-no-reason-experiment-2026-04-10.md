# Tracking No-Reason Experiment 2026-04-10

## Goal

Evaluate an experiment where:

- tracking `select` does not output `reason`
- no internal `reason` is retained for rewrite input
- tracking memory schema stays unchanged
- background rewrite remains asynchronous

## Setup

- model: `qwen3.5-flash`
- sample sequences:
  - hard sample: `corridor2`, frame `frame_000147`
  - easy sample: `room`, frame `frame_000026`
- baseline:
  - current full `track` prompt
  - current full `select_track_target` output contract
- experiment:
  - remove `reason` from output contract
  - add instruction `不要输出 reason 字段`
  - do not pass `confirmation_reason` into rewrite input
  - keep memory output schema unchanged

## Track Latency: 3-Run Comparison

| Case | Avg Latency | Min | Max | Avg Output Chars |
| --- | ---: | ---: | ---: | ---: |
| baseline `corridor2` | 2.359s | 1.766s | 2.881s | 493.3 |
| no-reason `corridor2` | 2.563s | 1.712s | 3.301s | 377.3 |
| baseline `room` | 3.304s | 2.592s | 3.880s | 636.3 |
| no-reason `room` | 2.915s | 1.999s | 4.414s | 419.7 |

Initial 3-run results were noisy.

## Track Latency: 6-Run Stability Check on Corridor2

| Case | Avg Latency | Median | Min | Max | Avg Output Chars |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | 3.497s | 3.572s | 1.943s | 5.377s | 517.2 |
| no-reason | 2.677s | 2.512s | 2.150s | 3.580s | 384.3 |

Measured gain on `corridor2` after removing `reason`:

- latency reduced by about `0.82s`
- relative reduction about `23.4%`

## Async Rewrite Check

Using the no-reason `track` output from `corridor2`:

- `confirmation_reason` was not passed into rewrite input
- rewrite still ran through the async/background path

Observed result:

- rewrite status: `processed`
- background rewrite latency: `1.555s`
- pending rewrite queue cleared successfully
- written memory keys remained:
  - `core`
  - `front_view`
  - `back_view`
  - `distinguish`

Observed written lengths:

- `core`: `65`
- `front_view`: `0`
- `back_view`: `63`
- `distinguish`: `0`

## Conclusion

### 1. Removing `reason` alone can reduce hot-path latency

On the more stable `corridor2` 6-run comparison, the no-reason version was faster by about `0.82s`.

### 2. But the gain is smaller than removing both `reason` and rich evidence

This experiment still kept `candidate_checks`, so the model continued to output a fair amount of explanatory text through `candidate_checks[].evidence`.

### 3. Async rewrite is operationally OK without `reason`

The async writeback path still completed successfully, and memory schema remained unchanged.

### 4. What this experiment proves and does not prove

It proves:

- no-reason hot path can be faster
- async rewrite still works without `confirmation_reason`
- memory schema does not need to change

It does not yet prove:

- long-run tracking accuracy is unchanged
- memory quality is identical without `confirmation_reason`

That would require a benchmark rerun under the no-reason configuration.
