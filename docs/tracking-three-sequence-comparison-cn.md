# 四序列对照表

当前文档展示最新的本地四序列 benchmark，对应 `2026-04-11` 的 no-reason 版本：

- 走廊场景一（`corridor1`）
- 走廊场景二（`corridor2`）
- 实验室走廊（`lab_corridor`）
- 房间场景（`room`）

## 对照表

| 方法 | 走廊场景一 | 走廊场景二 | 实验室走廊 | 房间场景 |
| --- | ---: | ---: | ---: | ---: |
| Zhong’s Method [29] | 63.8 | 66.8 | 75.8 | 44.7 |
| SiamRPN++ [30] | 44.8 | 55.9 | 46.1 | 42.6 |
| STARK [31] | 44.3 | 83.8 | 73.1 | 65.8 |
| SORT [32] + RPF-ReID | 67.3 | 37.9 | 31.1 | 82.4 |
| OC-SORT [33] + RPF-ReID | 67.3 | 37.9 | 31.1 | 82.4 |
| ByteTrack [34] + RPF-ReID | 69.1 | 20.2 | 54.2 | 82.4 |
| 纯 YOLO + ByteTrack（本地） | 27.74 | 23.76 | 18.92 | 42.86 |
| 当前策略（本地，no-reason） | **78.38** | **93.85** | **94.19** | **100.00** |

## 说明

- `纯 YOLO + ByteTrack（本地）` 来源：`.runtime/benchmark_yolo_bytetrack_full.json`
- `当前策略（本地，no-reason）` 来源：
  - `corridor1`: `.runtime/benchmark_corridor1_qwen35flash_no_reason_rebind_fsm_2026-04-11.json`
  - `corridor2`: `.runtime/benchmark_corridor2_qwen35flash_no_reason_rebind_fsm_2026-04-11.json`
  - `lab_corridor`: `.runtime/benchmark_labcorridor_qwen35flash_no_reason_rebind_fsm_2026-04-11.json`
  - `room`: `.runtime/benchmark_room_qwen35flash_no_reason_rebind_fsm_2026-04-11.json`
- 旧的 `2026-04-10` flash 结果见：
  - [tracking-benchmark-2026-04-10-qwen35flash.md](/Users/huzujun/Desktop/new/tracking_agent/docs/tracking-benchmark-2026-04-10-qwen35flash.md)
- 最新 no-reason benchmark 汇总见：
  - [tracking-no-reason-benchmark-2026-04-11.md](/Users/huzujun/Desktop/new/tracking_agent/docs/tracking-no-reason-benchmark-2026-04-11.md)
