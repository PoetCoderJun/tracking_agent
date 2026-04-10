# Tracking Benchmark Log 2026-04-04

## Summary

This run benchmarked the current local `YOLO + ByteTrack` tracking path against the custom dataset under `tests/dataset` using a paper-aligned sequence success-rate metric.

Raw output:

- `.runtime/benchmark_yolo_bytetrack_full.json`

Implemented benchmark code:

- `capabilities/tracking/benchmark.py`
- `tests/test_tracking_benchmark.py`

## Command

```bash
./.venv/bin/python -m capabilities.tracking.benchmark \
  --dataset-root tests/dataset \
  --device cpu \
  --output-json .runtime/benchmark_yolo_bytetrack_full.json
```

## Evaluation Protocol

- Metric: sequence-level success rate
- Success rule: predicted bbox center is within `50 px` of the ground-truth bbox center
- GT source: `labels.txt` in each sequence directory
- Zero-sized GT boxes such as `0 0 0 0` are skipped because the target is not visibly scoreable in that frame
- Initialization rule: bind the target to the highest-IoU detection on the first labeled frame, then keep following the same `track_id`

This evaluates the current `YOLO + ByteTrack` tracker path only. It does not include the paper's `RPF-ReID` or `OCL` components.

## Results

| Sequence | Evaluated Frames | Predicted Frames | Success Frames | Success Rate |
| --- | ---: | ---: | ---: | ---: |
| corridor1 | 1103 | 306 | 306 | 27.74% |
| corridor2 | 3817 | 923 | 907 | 23.76% |
| lab_corridor | 4567 | 864 | 864 | 18.92% |
| room | 567 | 243 | 243 | 42.86% |
| overall | 10054 | - | 2320 | 23.08% |

Additional observations from the raw report:

- `corridor1` mean center distance when the bound track exists: `2.75 px`
- `corridor2` mean center distance when the bound track exists: `4.88 px`
- `lab_corridor` mean center distance when the bound track exists: `5.00 px`
- `room` mean center distance when the bound track exists: `2.14 px`

## Comparison Against Paper Table I

Compared against the paper row `ByteTrack + RPF-ReID` on the same four custom sequences:

| Sequence | This Run: YOLO + ByteTrack | Paper: ByteTrack + RPF-ReID | Gap |
| --- | ---: | ---: | ---: |
| corridor1 | 27.74% | 69.1% | -41.36 |
| corridor2 | 23.76% | 20.2% | +3.56 |
| lab_corridor | 18.92% | 54.2% | -35.28 |
| room | 42.86% | 82.4% | -39.54 |

## Interpretation

- The current tracker does not reproduce the paper's `ByteTrack + RPF-ReID` level on three of the four custom sequences.
- The main failure mode is not bbox precision after a target is bound.
- The main failure mode is target persistence across time: `predicted_frames` is much lower than `evaluated_frames`, which means the tracker often loses the original `track_id`.
- This is consistent with the paper's claim that plain tracking needs an additional ReID or rebinding layer to recover through long variation, occlusion, and distractors.

## Next Experiment Direction

The next experiment should add a lightweight rebinding or ReID layer on top of the current tracker benchmark instead of tuning bbox precision. The current numbers suggest that target identity continuity is the bottleneck, not localization quality.
