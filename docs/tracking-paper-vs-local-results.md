# Tracking Paper Vs Local Results

## Original Paper Table

Source table columns:

- `corridor1†`
- `corridor2†`
- `lab-corridor†`
- `room†`
- `public dataset [5]`


| Methods | corridor1 | lab-corridor | corridor2 | room |
| --- | ---: | ---: | ---: | ---: |
| Zhong’s Method | 63.8 | 75.8 | 66.8 | 44.7 |
| SiamRPN++ | 44.8 | 46.1 | 55.9 | 42.6 |
| STARK | 44.3 | 73.1 | 83.8 | 65.8 |
| ByteTrack | 27.74 | 18.92 | 23.76 | 42.86 |
| SORT + RPF-ReID | 67.3 | 31.1 | 37.9 | 82.4 |
| OC-SORT + RPF-ReID | 67.3 | 31.1 | 37.9 | 82.4 |
| ByteTrack + RPF-ReID | 69.1 | 54.2 | 20.2 | 82.4 |
| ByteTrack + TrackingAgent (no-reason) | **78.38** | **94.19** | **93.85** | **100.00** |

## Our Local Results

### Pure YOLO + ByteTrack

This is the plain tracker baseline without our current rebind strategy.

Source:

- `.runtime/benchmark_yolo_bytetrack_full.json`

| Methods | corridor1† | corridor2† | lab-corridor† | room† | public dataset [5] |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pure YOLO + ByteTrack (ours) | 27.74 | 23.76 | 18.92 | 42.86 | N/A |

### Current Tracking Strategy

Current strategy summary:

- `rebind_fsm`
- tracker fps `8`
- no `reason` field in tracking select output
- async/background rewrite writeback
- keep tracking memory schema unchanged

Current best files:

- `corridor1`: `.runtime/benchmark_corridor1_qwen35flash_no_reason_rebind_fsm_2026-04-11.json`
- `corridor2`: `.runtime/benchmark_corridor2_qwen35flash_no_reason_rebind_fsm_2026-04-11.json`
- `lab_corridor`: `.runtime/benchmark_labcorridor_qwen35flash_no_reason_rebind_fsm_2026-04-11.json`
- `room`: `.runtime/benchmark_room_qwen35flash_no_reason_rebind_fsm_2026-04-11.json`

| Methods | corridor1† | corridor2† | lab-corridor† | room† | public dataset [5] |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current strategy (ours, no-reason) | 78.38 | 93.85 | 94.19 | 100.00 | N/A |

## Focused Comparison To ByteTrack + RPF-ReID

| Methods | corridor1† | corridor2† | lab-corridor† | room† |
| --- | ---: | ---: | ---: | ---: |

## Notes

- The paper table includes `public dataset [5]`; our local runs above only cover the custom sequences currently stored under `tests/dataset`.
- Our current evaluation pipeline is not a verbatim reproduction of the paper runtime. It is a local robot-kernel rebind benchmark built on top of `YOLO + ByteTrack` with custom rebinding and memory logic.
- Our latest no-reason runtime no longer shows a degradation tradeoff on the four custom sequences; all four sequences are now at or above the previous local flash baseline.
- Our local `corridor1`, `corridor2`, `lab-corridor`, and `room` all outperform the paper's `ByteTrack + RPF-ReID` row under our current benchmark setup, so these numbers should still be interpreted as local-system results rather than like-for-like paper reproduction.
- Historical flash and no-reason benchmark logs:
  - [tracking-benchmark-2026-04-10-qwen35flash.md](/Users/huzujun/Desktop/new/tracking_agent/docs/tracking-benchmark-2026-04-10-qwen35flash.md)
  - [tracking-no-reason-benchmark-2026-04-11.md](/Users/huzujun/Desktop/new/tracking_agent/docs/tracking-no-reason-benchmark-2026-04-11.md)
