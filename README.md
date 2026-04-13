# Robot Agent Runtime

一个面向机器人的 `chat-first` Embodied Agent Kernel。

它关注的是机器人的 `System 2`：以对话为入口，以环境感知为依据，让 Agent 在物理世界里形成 `观察 -> 思考 -> 行动 -> 验证 -> 恢复` 的最小闭环。当前仓库以 `tracking` 和其它 skills 作为能力样例。

## Why

机器人底层的检测、跟踪、导航、避障、本体控制属于低延迟的 `System 1`。这个项目关心的是更上层的 `System 2`：当用户通过自然语言提出开放式目标后，Agent 如何读取当前世界、拆解任务、选择能力、提交动作、验证结果，并在偏差出现时恢复。

这套内核坚持几条硬边界：

- 入口是 `chat / script / interface`，不是感知线程自己驱动高层任务。
- `perception` 是唯一常驻输入层，持续提供世界快照，但不拥有高层编排权。
- `runner` 保持单一路径和单一动作提交权。
- agent-owned state 只有一份持久化 session truth。
- `tracking-init` 是一次性 skill；持续跟踪由同一条 session 内部的 mini Re/Act follow-up 承接。

`tracking` 是这套架构的 proof point，因为它天然要求：

- 自然语言指定目标
- 基于当前世界快照确认身份
- 遮挡 / 短时离场后的 rebind / recovery
- 图文 memory 维护
- 在持续运行中反复验证“当前跟踪的人是不是还是同一个人”

## Demo

最小可工作的主路径是 2 个进程，viewer 是可选界面：

终端 1，启动 write environment：

```bash
uv run robot-agent-environment-writer --source 0
```

终端 2，启动 PI TUI：

```bash
uv run e-agent
```

然后在 `pi` 中输入：

```text
开始跟踪穿黑衣服的人
继续跟踪
```

这条链路里会发生：

- write environment 持续写入 `perception/snapshot.json`
- `tracking-init` skill 读取当前世界快照并确认目标
- session 中写入 tracking state、text memory、image crop memory
- `e-agent` 在同一条 session 内继续跑 continuous tracking mini Re/Act
- tracking/runtime 会把 viewer 需要的最新结果写到 `./.runtime/agent-runtime/viewer/latest.json` 和 `latest.jpg`
- viewer 只读这些本地文件，不参与调度

## Features

- `chat-first`：PI 对话是主入口。
- always-on perception：write environment 持续写世界快照和同帧 system1 结果。
- single runner path：高层任务推进和状态提交都走同一条 runner 路径。
- single session truth：agent-owned state 只有一份持久化 truth。
- tracking 双段式：`tracking-init` 做初始化，continuous mini-agent 做 review / rebind。
- read-only viewer：viewer 只负责观察状态，不承担调度逻辑。
- benchmark 对齐 runtime：tracking benchmark 默认走当前 continuous-tracking runtime path。

## Quick Start

环境要求：

- Python `3.9`
- `uv`
- `pi`（`e-agent` 默认会从 `PATH` 里直接执行它）

安装 `uv`：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

macOS 也可以直接用：

```bash
brew install uv
```

安装 `pi`（全局安装即可，`uv run e-agent` 默认直接调用 `PATH` 里的 `pi`）：

```bash
npm install -g @mariozechner/pi-coding-agent
pi --help
```

安装依赖：

```bash
uv sync
```

如果当前 shell 需要 `.ENV` 里的凭证：

```bash
set -a && source .ENV && set +a
```

### 1. 启动 write environment

摄像头：

```bash
uv run robot-agent-environment-writer --source 0
```

文件流：

```bash
uv run robot-agent-environment-writer --source tests/fixtures/demo_video.mp4
```

对文件流，运行时会自动使用实时播放默认行为，不需要再额外传其它参数。

### 2. 启动 PI Agent TUI

```bash
uv run e-agent
```

### 3. 可选启动 viewer UI

```bash
cd interfaces/viewer
npm install
npm run dev
```

`e-agent` 默认会：

- bootstrap active session
- 以前台 supervisor 的方式拉起 `pi`
- 只加载仓库内 project skills
- 在同一条 session 上接管 continuous tracking follow-up

## Architecture

当前仓库的最小链路是：

```text
write environment
    -> perception snapshot
    -> same-frame system1 result

PI TUI / e-agent
    -> chat turn
    -> skill selection
    -> runner commit
    -> continuous tracking mini Re/Act

viewer
    -> read-only session + perception inspection
```

目录边界：

- `world/`: 常驻输入层。写 perception、frame artifact、snapshot、system1 result。
- `agent/`: active session、runner、state commit、`e-agent` supervisor。
- `capabilities/`: runtime-owned capability logic，例如 tracking runtime。
- `skills/`: 面向 `pi` 的 skill contract 和 skill-local helper，例如 tracking init、tts、feishu、web-search。
- `interfaces/`: viewer 本地快照读取等只读界面。

tracking 的核心结构：

```text
tracking-init skill
    -> 确认目标
    -> 初始化 memory
    -> 写入 tracking state

continuous tracking mini-agent
    -> derive trigger
    -> Re(snapshot)
    -> Act(decision)
    -> Commit(result)
```

这里的 `loop` 指的是这段内部 continuous mini Re/Act 逻辑，不是独立 stack。

## Usage

### 1. PI 里触发 tracking init，然后自动进入持续跟踪

先启动：

```bash
uv run robot-agent-environment-writer --source 0
uv run e-agent
```

然后在 `pi` 里说：

```text
开始跟踪穿黑衣服的人
```

成功完成 `tracking-init` 后，Agent 会在同一条 session 内自己接手 continuous tracking，不需要再单独起一个 tracking stack。

如果要看 UI，再单独启动：

```bash
cd interfaces/viewer
npm run dev
```

### 2. Benchmark 验证

直接跑默认 benchmark：

```bash
uv run robot-agent-tracking-benchmark
```

只跑某一个序列：

```bash
uv run robot-agent-tracking-benchmark --sequence corridor1
```

保存 JSON 报告：

```bash
uv run robot-agent-tracking-benchmark \
  --sequence corridor1 \
  --output-json ./.runtime/tracking-benchmark/corridor1.json
```

### 3. 查看当前状态

查看 active session：

```bash
uv run robot-agent session-show
```

查看 perception 最新 frame：

```bash
uv run robot-agent-perception latest-frame
```
