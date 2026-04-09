# Robot Agent Runtime

这是项目当前的最简运行文档，只保留安装和启动相关内容。

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

## 运行模型

当前启动面分成三块：

- `environment writer`：唯一常驻组件，持续写入 perception，并对同一帧同步写入 system1 结果。
- `active session`：主 runner 创建并持有的会话标识。skills 和 runtime 都从这里读写 agent state，但不负责偷偷创建或切换它。
- `pi`：聊天入口。它进入项目 skill 后，skill 再通过 `backend.cli` 访问当前 active session。

如果你需要 tracking 的持续轮询与自动继续跟踪，还要再单独启动一次：

- `tracking.loop`：唯一的 tracking runner，负责对已绑定目标做持续 track turn。

## 只启动 PI

这是最小聊天流程，适合只想让 `pi` 进来读当前 perception、调用 skills、手动触发 turn 的场景。

1. 启动常驻环境写入：

```bash
uv run robot-agent-environment-writer --source 0
```

2. 直接启动主 runner：

```bash
uv run e-agent
```

说明：

- `e-agent` 会先 bootstrap 主 runner session，然后直接 `exec` 进 `pi`。
- 会显式关闭 `pi` 的默认 skills 发现，只加载仓库内 `skills/` 和你额外传入的 `--skill`。
- `e-agent` 默认直接进入 `pi`，避免交互 TUI 在 macOS 沙箱里触发终端 raw mode 错误。
- 如果你明确要把 `pi` 放进 macOS `sandbox-exec`，再显式传 `--pi-sandbox`。
- 开启 `--pi-sandbox` 后，如果某个 workflow 还需要额外写目录，可以追加 `--pi-writable-dir /abs/path`。
- 如果你要固定 session id：

```bash
uv run e-agent --session-id sess_001
```

- 如果你要重置后再进 `pi`：

```bash
uv run e-agent --fresh
```

- 这条流程不会自动拉起 `tracking.loop`。
- 所以用户在 `pi` 里仍然可以做目标选择、问状态、调用 skill。
- 但“绑定目标后自动持续继续跟踪”不在这条最小流程里。

## 完整 Tracking 启动

如果你要 environment writer + websocket viewer 一起跑，直接用 stack：

摄像头：

```bash
uv run robot-agent-tracking-stack --source 0
```

视频：

```bash
uv run robot-agent-tracking-stack \
  --source backend/tests/fixtures/demo_video.mp4 \
  --realtime-playback
```

如果要把前端一起拉起：

```bash
uv run robot-agent-tracking-stack \
  --source backend/tests/fixtures/demo_video.mp4 \
  --realtime-playback \
  --start-frontend
```

stack 启动后，再执行：

```bash
uv run e-agent
```

如果你还需要持续 tracking loop，再单独开一个终端：

```bash
uv run robot-agent-tracking-loop \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent
```

## 手动分开启动 Tracking

如果你不想用 stack，也可以分开起：

1. environment writer：

```bash
uv run robot-agent-environment-writer --source 0
```

2. tracking runner：

```bash
uv run robot-agent-tracking-loop \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent
```

3. 主 runner：

```bash
uv run e-agent
```

## 常用调试命令

看当前 active session：

```bash
uv run robot-agent session-show --state-root ./.runtime/agent-runtime
```

如果你确实想手动固定或重置主 session，仍然可以显式执行底层命令：

```bash
uv run robot-agent runner-bootstrap --session-id sess_001 --state-root ./.runtime/agent-runtime --fresh
```

看全局 perception 最新 frame：

```bash
uv run robot-agent-perception latest-frame --state-root ./.runtime/agent-runtime
```

直接看全局 perception snapshot.json：

```bash
cat ./.runtime/agent-runtime/perception/snapshot.json
```

直接看全局 system1 snapshot.json：

```bash
cat ./.runtime/agent-runtime/system1/snapshot.json
```

手动做一次确定性 tracking init：

```bash
uv run robot-agent tracking-init \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent \
  --text "开始跟踪穿黑衣服的人"
```

手动做一次确定性 tracking track：

```bash
uv run robot-agent tracking-track \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent
```
