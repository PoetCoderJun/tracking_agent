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

- `environment writer`：唯一常驻组件，持续写入 perception，并把同一帧的 system1 结果一起落进同一份 perception snapshot。
- `active session`：主 runner 创建并持有的会话标识。skills 和 runtime 都从这里读写 agent state，但不负责偷偷创建或切换它。
- `pi`：聊天入口。`e-agent` 现在会以前台 supervisor 的形式拉起 `pi` 子进程，并在同一条 session 上接管 tracking 的持续 follow-up turn。

## 当前内核结构

当前代码结构按 `2025 Q1答辩.pptx` 第 8/9 页收口为：

- `agent/`：唯一 runner path、session truth、continuation 和 turn orchestration。
- `world/`：环境层；`perception`、system1 input、snapshot、cache、keyframe 与 frame artifacts 都在这里落盘。
- `capabilities/`：模型可调用的统一能力面；`tracking`、`tts`、`feishu`、`web_search`、`describe_image`、`actions` 都按 capability 归属。
- `skills/`：给 `pi` 的 skill contract 和 skill-local helper。skill 保持即插即用；仓库不会再为普通 skill 在平台层手写一套镜像 runtime。skill 如果需要附带执行辅助或 viewer 扩展，优先自带在自己的 `scripts/` 里。
- `interfaces/`：共享状态读取界面；当前 `viewer` 只在这里，不参与调度。
- `scripts/`：薄入口；只做参数解析、环境拼装和 owner dispatch。

当前主路径不再保留额外的 tracking CLI 包装层，也不再依赖脚本级 loop/viewer wrapper 来进入核心运行逻辑。

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

- `e-agent` 会先 bootstrap 主 runner session，然后保持为前台 supervisor，并拉起 `pi` 子进程。
- 会显式关闭 `pi` 的默认 skills 发现，只加载仓库内 `skills/` 和你额外传入的 `--skill`。
- `e-agent` 默认直接拉起 `pi`，避免交互 TUI 在 macOS 沙箱里触发终端 raw mode 错误。
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

- 在 `pi` 里成功完成 tracking-init 这一步后，会自动激活同 session 的 tracking follow-up。
- 这段 follow-up 不是 skill，而是 `e-agent` supervisor 持有的持续业务流程。
- follow-up 默认按 3 秒 cadence 继续做 `tracking-track`，如果当前目标 `track id` 丢失，也会立即触发一次恢复判断。
- 如果在 `pi` 里重新指定了新的跟踪对象，当前 session 的 tracking memory/runtime 标记会被重置，并切到新的目标继续 follow-up。

## 完整 Tracking 启动

如果你要 environment writer + websocket viewer 一起跑，直接用 stack：

摄像头：

```bash
uv run robot-agent-tracking-stack --source 0
```

视频：

```bash
uv run robot-agent-tracking-stack \
  --source tests/fixtures/demo_video.mp4 \
  --realtime-playback
```

如果要把前端一起拉起：

```bash
uv run robot-agent-tracking-stack \
  --source tests/fixtures/demo_video.mp4 \
  --realtime-playback \
  --start-frontend
```

stack 启动后，再执行：

```bash
uv run e-agent
```

viewer 会跟随当前 active session，显示 tracking 状态、当前 memory、最新回复和展示帧。

## 手动分开启动 Tracking

如果你不想用 stack，也可以分开起：

1. environment writer：

```bash
uv run robot-agent-environment-writer --source 0
```

2. 主 runner：

```bash
uv run e-agent
```

如果你要 viewer websocket：

```bash
uv run python -m interfaces.viewer.stream --state-root ./.runtime/agent-runtime
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

查看同一份 perception snapshot 里的 system1 字段：

```bash
cat ./.runtime/agent-runtime/perception/snapshot.json
```

手动做一次 skill-local tracking init：

```bash
python -m skills.tracking.scripts.init_turn \
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

手动做一次 skill-local tts speak：

```bash
python -m skills.tts.scripts.speak_turn \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent \
  --text "实验开始，请注意安全。"
```

说明：

- 上面这条只用于确定性检查。
- 正常主路径下，不需要再手动启动单独的 `robot-agent-tracking-loop` 来保持持续跟踪；这条持续流程由 `scripts/e_agent.py` 接管。
