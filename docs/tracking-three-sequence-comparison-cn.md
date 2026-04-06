# 三序列对照表

仅保留以下三个本地 benchmark：

- 走廊场景二（`corridor2`）
- 实验室走廊（`lab_corridor`）
- 房间场景（`room`）

已移除：

- `corridor1`
- `public dataset [5]`

## 对照表

| 方法 | 走廊场景二 | 实验室走廊 | 房间场景 |
| --- | ---: | ---: | ---: |
| Zhong’s Method [29] | 66.8 | 75.8 | 44.7 |
| SiamRPN++ [30] | 55.9 | 46.1 | 42.6 |
| STARK [31] | 83.8 | 73.1 | 65.8 |
| SORT [32] + RPF-ReID | 37.9 | 31.1 | 82.4 |
| OC-SORT [33] + RPF-ReID | 37.9 | 31.1 | 82.4 |
| ByteTrack [34] + RPF-ReID | 20.2 | 54.2 | 82.4 |
| 纯 YOLO + ByteTrack（本地） | 23.76 | 18.92 | 42.86 |
| 当前策略（本地） | 62.49 | 90.39 | 87.42 |

## 说明

- `纯 YOLO + ByteTrack（本地）` 来源：`.runtime/benchmark_yolo_bytetrack_full.json`
- `当前策略（本地）` 来源：
  - `corridor2`: `.runtime/benchmark_corridor2_rebind_fsm_boundreview.json`
  - `lab_corridor`: `.runtime/benchmark_labcorridor_rebind_fsm_boundreview.json`
  - `room`: `.runtime/benchmark_room_rebind_fsm_boundreview.json`
