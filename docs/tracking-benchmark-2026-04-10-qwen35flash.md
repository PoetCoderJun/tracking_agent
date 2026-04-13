# Tracking Benchmark Log 2026-04-10

## Setup

- run time: `2026-04-10 23:22:01 HKT`
- pipeline: `rebind_fsm`
- tracker fps: `8.0`
- observation interval: `1.0s`
- recovery trigger: `rebind_after_missed_frames = 1`
- detector/tracker: `yolov8n.pt + bytetrack.yaml`
- tracking init target selection model: `qwen3.5-flash`
- tracking continuous rebind selection model: `qwen3.5-flash`
- tracking memory rewrite model: `qwen3.5-flash`

## Results

| Sequence | Evaluated Frames | Predicted Frames | Success Frames | Success Rate | Mean Center Distance |
| --- | ---: | ---: | ---: | ---: | ---: |
| corridor1 | 37 | 33 | 28 | 75.68% | 45.26 px |
| corridor2 | 130 | 130 | 97 | 74.62% | 58.41 px |
| lab_corridor | 155 | 152 | 145 | 93.55% | 21.90 px |
| room | 20 | 20 | 20 | 100.00% | 2.99 px |

## Result Files

- `corridor1`: `.runtime/benchmark_corridor1_qwen35flash_rebind_fsm_2026-04-10.json`
- `corridor2`: `.runtime/benchmark_corridor2_qwen35flash_rebind_fsm_2026-04-10.json`
- `lab_corridor`: `.runtime/benchmark_labcorridor_qwen35flash_rebind_fsm_2026-04-10.json`
- `room`: `.runtime/benchmark_room_qwen35flash_rebind_fsm_2026-04-10.json`

## Notes

- This log records the current repository behavior after forcing tracking init, track, and memory rewrite onto `qwen3.5-flash`.
- These numbers use the current `rebind_fsm` benchmark implementation in this repository.
- They are not directly comparable to older docs that reported a different evaluation count or a different benchmark protocol.
