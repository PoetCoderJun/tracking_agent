# Robot Agent Runtime

这是项目的最简运行文档，只保留安装和启动相关内容。

## 安装

需要：

- Python `3.9`
- `uv`
- `pi`

安装项目依赖：

```bash
uv sync
```

如果当前 shell 需要 `.ENV` 里的凭证，先执行：

```bash
set -a && source .ENV && set +a
```

## 最简启动

1. 启动常驻 perception：

```bash
uv run python -m scripts.run_tracking_perception --source 0 --fresh-session
```

2. 创建一个 runtime session：

```bash
uv run robot-agent session-start
```

3. 直接启动 `pi`：

```bash
pi
```

## Tracking 启动

摄像头：

```bash
uv run python -m scripts.run_tracking_perception --source 0 --fresh-session
```

视频：

```bash
uv run python -m scripts.run_tracking_perception \
  --source backend/tests/fixtures/demo_video.mp4 \
  --fresh-session \
  --realtime-playback
```

如果要一键启动 tracking 环境，也可以直接跑：

```bash
uv run robot-agent-tracking-stack \
  --source backend/tests/fixtures/demo_video.mp4 \
  --realtime-playback
```

然后再执行：

```bash
uv run robot-agent session-start
pi
```

## 说明

- `pi` 是唯一的 agent TUI / runner。
- `perception` 是常驻的，独立于 session。
- 当前 skills 依赖 active session，所以在进入 `pi` 前仍要先执行一次 `uv run robot-agent session-start`。
