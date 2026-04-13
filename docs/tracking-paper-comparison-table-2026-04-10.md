# Tracking Paper Comparison Table 2026-04-10

这份文件提供一份新的论文用对比表，基于论文中的自定义场景结果列，并补入当前仓库最新的 `qwen3.5-flash` 版本结果。

## Paper-Ready Markdown Table

| Methods | corridor1† | corridor2† | lab-corridor† | room† |
| --- | ---: | ---: | ---: | ---: |
| Zhong’s Method [29] | 63.8 | 66.8 | 75.8 | 44.7 |
| SiamRPN++ [30] | 44.8 | 55.9 | 46.1 | 42.6 |
| STARK [31] | 44.3 | **83.8** | 73.1 | 65.8 |
| SORT [32] + RPF-ReID | 67.3 | 37.9 | 31.1 | 82.4 |
| OC-SORT [33] + RPF-ReID | 67.3 | 37.9 | 31.1 | 82.4 |
| ByteTrack [34] + RPF-ReID | 69.1 | 20.2 | 54.2 | 82.4 |
| ByteTrack + TrackingAgent (Qwen3.5-Flash, ours) | **75.68** | 74.62 | **93.55** | **100.00** |

## LaTeX Table

```tex
\begin{table}[t]
\centering
\caption{Success rate (\%) comparison on four custom sequences.}
\label{tab:tracking-custom-sequences}
\begin{tabular}{lcccc}
\toprule
Methods & corridor1$\dagger$ & corridor2$\dagger$ & lab-corridor$\dagger$ & room$\dagger$ \\
\midrule
Zhong's Method~\cite{ref29} & 63.8 & 66.8 & 75.8 & 44.7 \\
SiamRPN++~\cite{ref30} & 44.8 & 55.9 & 46.1 & 42.6 \\
STARK~\cite{ref31} & 44.3 & \textbf{83.8} & 73.1 & 65.8 \\
SORT + RPF-ReID~\cite{ref32} & 67.3 & 37.9 & 31.1 & 82.4 \\
OC-SORT + RPF-ReID~\cite{ref33} & 67.3 & 37.9 & 31.1 & 82.4 \\
ByteTrack + RPF-ReID~\cite{ref34} & 69.1 & 20.2 & 54.2 & 82.4 \\
ByteTrack + TrackingAgent (Qwen3.5-Flash, ours) & \textbf{75.68} & 74.62 & \textbf{93.55} & \textbf{100.00} \\
\bottomrule
\end{tabular}
\end{table}
```

## Result Sources For Our Row

- `corridor1`: `.runtime/benchmark_corridor1_qwen35flash_rebind_fsm_2026-04-10.json`
- `corridor2`: `.runtime/benchmark_corridor2_qwen35flash_rebind_fsm_2026-04-10.json`
- `lab_corridor`: `.runtime/benchmark_labcorridor_qwen35flash_rebind_fsm_2026-04-10.json`
- `room`: `.runtime/benchmark_room_qwen35flash_rebind_fsm_2026-04-10.json`

## Suggested Caption Note

如果你准备把这张表直接放进论文，建议在 caption 或正文里补一句：

`Our row is measured with the current TrackingAgent rebind benchmark in this repository and should be interpreted as the system-level result of our implementation.`

如果你想更严格一些，可以改成：

`Our row is produced by the current TrackingAgent system benchmark and is not a verbatim reproduction of the original paper runtime.`
