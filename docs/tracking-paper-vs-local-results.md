# Tracking Paper Vs Local Results

## Original Paper Table

Source table columns:

- `corridor1†`
- `corridor2†`
- `lab-corridor†`
- `room†`
- `public dataset [5]`

| Methods | corridor1† | corridor2† | lab-corridor† | room† | public dataset [5] |
| --- | ---: | ---: | ---: | ---: | ---: |
| Zhong’s Method [29] | 63.8 | 66.8 | 75.8 | 44.7 | 75.8 |
| SiamRPN++ [30] | 44.8 | 55.9 | 46.1 | 42.6 | 93.6 |
| STARK [31] | 44.3 | 83.8 | 73.1 | 65.8 | 96.5 |
| SORT [32] + RPF-ReID | 67.3 | 37.9 | 31.1 | 82.4 | 96.1 |
| OC-SORT [33] + RPF-ReID | 67.3 | 37.9 | 31.1 | 82.4 | 96.1 |
| ByteTrack [34] + RPF-ReID | 69.1 | 20.2 | 54.2 | 82.4 | 96.3 |

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
- `rebind_after_missed_frames = 1`
- first `3` stable-bound frames after bind/rebind: review every frame
- after that: review every `5` stable-bound frames
- no `excluded_track_ids` filtering
- no historical ID dependency in `track`
- use front/back reference crops in `track`
- proactive front/back anchor accumulation
- bound-state review
- rewrite gating

Current best files:

- `corridor1`: `.runtime/benchmark_corridor1_rebind_fsm_rewritegate.json`
- `corridor2`: `.runtime/benchmark_corridor2_rebind_fsm_boundreview.json`
- `lab_corridor`: `.runtime/benchmark_labcorridor_rebind_fsm_boundreview.json`
- `room`: `.runtime/benchmark_room_rebind_fsm_boundreview.json`

| Methods | corridor1† | corridor2† | lab-corridor† | room† | public dataset [5] |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current strategy (ours) | 34.58 | 62.49 | 90.39 | 87.42 | N/A |

## Focused Comparison To ByteTrack + RPF-ReID

| Methods | corridor1† | corridor2† | lab-corridor† | room† |
| --- | ---: | ---: | ---: | ---: |
| ByteTrack [34] + RPF-ReID | 69.1 | 20.2 | 54.2 | 82.4 |
| Pure YOLO + ByteTrack (ours) | 27.74 | 23.76 | 18.92 | 42.86 |
| Current strategy (ours) | 34.58 | 62.49 | 90.39 | 87.42 |

## Notes

- The paper table includes `public dataset [5]`; our local runs above only cover the custom sequences currently stored under `backend/tests/dataset`.
- Our current evaluation pipeline is not a verbatim reproduction of the paper runtime. It is a local robot-kernel rebind benchmark built on top of `YOLO + ByteTrack` with custom rebinding and memory logic.
- Our local `corridor1` result still lags badly and remains the weakest custom sequence.
- Our local `corridor2`, `lab-corridor`, and `room` now outperform the paper's `ByteTrack + RPF-ReID` row under our current benchmark setup, so these numbers should be interpreted as local-system results rather than like-for-like paper reproduction.

| Methods | corridor2 | lab-corridor | room |
| --- | ---: | ---: | ---: |
| Zhong’s Method | 66.8 | 75.8 | 44.7 |
| SiamRPN++ | 55.9 | 46.1 | 42.6 |
| STARK | 83.8 | 73.1 | 65.8 |
| SORT + RPF-ReID | 37.9 | 31.1 | 82.4 |
| OC-SORT + RPF-ReID | 37.9 | 31.1 | 82.4 |
| ByteTrack + RPF-ReID | 20.2 | 54.2 | 82.4 |
| ByteTrack | 23.76 | 18.92 | 42.86 |
| ByteTrack + TrackingAgent | 62.49 | 90.39 | 87.42 |
