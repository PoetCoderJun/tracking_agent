# Tracking Single-Turn Latency Experiments 2026-04-10

## Goal

Measure the current single-turn latency after moving tracking memory rewrite off the critical path, and check whether the main bottleneck comes more from:

- large input context
- verbose output fields such as `reason` and `candidate_checks`

## Setup

- model: `qwen3.5-flash`
- backend: current DashScope-compatible endpoint from local `.ENV`
- sample type: real benchmark artifacts from current repository runtime output
- critical-path measurement target: `track select`
- background measurement target: `rewrite memory`
- repeats per case: `3`

Representative samples:

- hard sample: `corridor2`, frame `frame_000147`
- easy sample: `room`, frame `frame_000026`

## Cases

### Track Select

1. `track_full_corridor2`
   - current full prompt
   - current full output contract
   - includes `reason`, `reject_reason`, `needs_clarification`, `clarification_question`, `candidate_checks`
2. `track_full_room`
   - same as above, but on room sample
3. `track_short_output_corridor2`
   - same full prompt and same images
   - output reduced to `decision + bounding_box_id + text`
   - no `reason`, no `candidate_checks`
4. `track_short_input_output_corridor2`
   - compressed input prompt
   - same images
   - same short output contract as case 3

### Rewrite Memory

5. `rewrite_full_corridor2`
   - current full memory update prompt
   - current full memory JSON output
6. `rewrite_short_corridor2`
   - compressed rewrite prompt
   - reduced output to `core + reference_view`

## Results

| Case | Avg Latency | Min | Max | Avg Output Chars | Prompt Chars | Images |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `track_full_corridor2` | 2.876s | 2.427s | 3.279s | 479.3 | 2932 | 3 |
| `track_full_room` | 3.677s | 3.042s | 4.856s | 619.3 | 2751 | 2 |
| `track_short_output_corridor2` | 1.792s | 1.619s | 2.123s | 195.7 | 2581 | 3 |
| `track_short_input_output_corridor2` | 1.438s | 1.143s | 2.023s | 75.0 | 563 | 3 |
| `rewrite_full_corridor2` | 2.902s | 2.853s | 2.981s | 589.0 | 1797 | 2 |
| `rewrite_short_corridor2` | 1.321s | 0.934s | 1.922s | 78.3 | 391 | 2 |

## End-To-End Critical Path Check

Measured on current code path for `corridor2` track select using `execute_select_tool(...)`:

- average `select_tool` wall time: `2.841s`
- average model elapsed time inside the tool: `2.792s`

This means almost all current critical-path latency is spent inside the model call, not in local overlay/crop/state code.

## Findings

### 1. The old 1.x-second behavior is still plausible

On the compressed `track_short_input_output_corridor2` case, the average latency was:

- `1.438s`

So if you aggressively reduce both prompt size and output size, a `1.xs` single-turn call is still realistic on the current endpoint.

### 2. Output verbosity is a major bottleneck

Compare:

- full track output on corridor2: `2.876s`
- same prompt, but no `reason` and no `candidate_checks`: `1.792s`

Latency dropped by:

- `1.084s`
- about `37.7%`

This is the cleanest evidence that verbose structured output is currently a major contributor.

### 3. Input context also matters, but less than output in this experiment

Compare:

- `track_short_output_corridor2`: `1.792s`
- `track_short_input_output_corridor2`: `1.438s`

After output had already been shortened, compressing the input further only saved:

- `0.354s`
- about `19.8%`

So in this setup, output reduction bought more latency than input reduction.

### 4. Rewrite was expensive, but it is now off the critical path

Full rewrite latency on the corridor2 sample was:

- `2.902s`

Short rewrite latency was:

- `1.321s`

So rewrite itself is also expensive, but after the recent async/background change it should no longer block the main tracking response path.

## Practical Recommendation

If your goal is lower live tracking latency, the highest-signal first move is:

- remove or heavily compress `reason`
- remove `candidate_checks` from the hot path

Only after that should you spend effort on prompt compression.

## Suggested Hot-Path Output

For the fastest online path, the response can likely be reduced to:

```json
{"decision":"track|wait","bounding_box_id":12|null,"text":"简短回复"}
```

Then, if you still need rich explanations, you can generate them only in:

- debugging mode
- offline analysis
- sampled audit turns rather than every turn
