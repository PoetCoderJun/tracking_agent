# Agent Architecture

## Goal

把仓库收成一个本地可直跑的 Agent Runtime：

- `backend` 只负责感知、记忆、运行时、动作接口
- `skills` 负责具体能力
- `tracking` 和 `speech` 都只是 skill，不是整个系统

这里不再引入服务端接口、前端面板、远程协议适配层。对人只保留一个本地 CLI：`robot-agent chat`。环境输入由独立的长期运行脚本写入持久化状态。

## Core Principles

1. `agent` 拥有 context 和 memory。
2. `persistence` 只负责 save/load。
3. `skills` 只消费 context、产出结果。
4. `runner` 只负责调用真实 `pi`。
5. 外部控制统一走本地 CLI，而不是额外的服务协议层。
6. perception 进程只写状态，不直接替 agent 做决策。
7. 自动持续跟踪由独立 loop 进程负责，不属于 tracking skill 本体。

## Minimal Structure

### `backend/perception/`

环境输入层：

- perception event dataclass
- 视频 FPS 探测
- 抽帧和事件落盘

### `backend/agent/`

Agent 核心：

- `context.py`: 当前轮可见上下文
- `memory.py`: user preferences、environment map、perception cache、skill cache
- `runtime.py`: ingest event、append chat、更新 memory
- `runner.py`: 写 turn context、调用 `pi`、回收通用结构化结果

### `backend/persistence/`

持久化层：

- `live_session_store.py`: 最近帧、对话、latest result、result history

### `backend/actions/`

动作执行层：

- `cli.py`: 机器人 CLI 命令封装

### `backend/cli.py`

本地唯一主入口：

- `chat`

### `.pi/settings.json`

Pi 原生发现配置：

- 把项目 `./skills` 暴露给 Pi
- backend 不再做自定义 skill loader

### `skills/tracking/`

tracking skill 本体：

- `SKILL.md`: 单轮 tracking 技能契约
- `references/`: 交互策略、输出契约、memory 契约
- `scripts/`: 本 skill 的确定性工具以及配套脚本

## Runtime Flow

1. 长期运行的 perception writer 产生视觉输入。
2. perception writer 把 observation、frame、detections 写进 runtime 和 agent memory，但不写入 chat history。
3. 用户调用 `robot-agent chat`，或 tracking loop 在有活动目标时定时触发一条“继续跟踪”chat。
4. `PiAgentRunner` 只把 turn context 路径交给 Pi，让 Pi 原生发现并决定 skill。
5. 被选中的 skill 按需用 Bash 读取 session 文件、agent memory、最新 frame 和 detections，并在需要时调用 skill 自己的脚本。
6. backend 只按通用结果 schema 写回 `latest_result` 与 `skill_cache[skill_name]`。
7. 动作层按需读取 `robot_response` 或 CLI command plan 去执行。

## Retention

- `session.json` 只保留最近的 `recent_frames`
- `sessions/<id>/frames/` 会删除已经脱离 `recent_frames` 的旧图片
- `events.jsonl` 由 perception writer 裁剪到最近若干行
- `skill_cache` 的字段由各个 skill 自己负责维护
- perception writer 只往 `state-root` 保留一份帧文件，避免双写带来的额外 IO
- tracking helper scripts 只保留视觉定位、memory rewrite、perception writer、可选 loop

## Why This Is Simpler

- 没有额外 backend service
- 没有 websocket/socket.io/http 协议面
- 没有 web 面板
- 没有多个分散 CLI
- skill 状态不再污染通用 session
- perception 与 chat 触发解耦
- observation 不再污染 `conversation_history`
- backend 不再保存 skill 专属脚本
- tracking skill 本体只保留 `SKILL.md + scripts + references`

也就是说，仓库里真正的核心就是：

`perception writer -> persisted state -> chat trigger -> pi runner -> skill -> actions`

这更符合第一性原理，也更接近“机器人本机直跑 agent”的实际形态。
