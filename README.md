# Robot Agent Runtime

这是一个运行在 robot / Pi 侧的 chat-first embodied agent kernel。

- `agent/` 是独立的 agent runner 与会话状态层
- `backend/` 是 perception、业务编排、状态管理和 `robot-agent chat`
- `backend/perception/cli.py` 是独立感知服务的查询入口，供本地 runner 通过 CLI 读取
- `viewer/` 是 tracking viewer 前端和 websocket stream
- `skills/` 提供 capability 实现，当前重点是 tracking、web_search 和 feishu
- `scripts/` 是兼容性薄壳，用来把 perception、轮询、viewer 这些进程跑起来
- `skills/tracking/` 是当前的目标选择 skill
- `skills/web_search/` 是基于 SkillHub 的网页搜索 skill
- `skills/feishu/` 是基于 SkillHub 能力包装的飞书通知 skill

## 推荐启动

当前推荐把 tracking 系统拆成 3 个长期进程，加上一个可选前端：

1. perception：持续写入检测与帧
2. tracking loop：按事件驱动 tracking continuation / recovery
3. viewer stream：输出 viewer websocket
4. frontend：可选的 viewer 前端

`scripts/run_tracking_stack.sh` 现在只是一个薄壳：
- 同时启动上面 4 个进程
- 为它们绑定同一个 `session_id`
- 给每路日志加前缀并打印

推荐先这样启动环境：

```bash
uv run robot-agent-tracking-stack \
  --source backend/tests/fixtures/demo_video.mp4 \
  --state-root ./.runtime/agent-runtime \
  --output-dir ./.runtime/tracking-perception \
  --artifacts-root ./.runtime/pi-agent \
  --device cpu \
  --tracker bytetrack.yaml \
  --realtime-playback
```

启动后：
- websocket 默认在 `ws://127.0.0.1:8765`
- tracking loop 会持续读取 perception 并在需要时触发 backend deterministic `track`
- stack 默认不启动前端，避免把 viewer 强耦合进主流程
- chat turn 默认通过外部 `pi` 二进制执行单轮 agent turn
- stack 不再强制内嵌 init；init 应该作为独立 chat turn 手动发起

如果你更看重可控性，也可以把 perception、loop、viewer 分开启动。


## 常用手工命令

只启动 perception：

```bash
uv run robot-agent-tracking-perception \
  --state-root ./.runtime/agent-runtime \
  --output-dir ./.runtime/tracking-perception \
  --device cpu \
  --tracker bytetrack.yaml \
  --interval-seconds 1
```

只启动前端：

```bash
bash scripts/run_tracking_frontend.sh \
  --host 127.0.0.1 \
  --port 5173 \
  --ws-url ws://127.0.0.1:8765
```

如果 backend 改了端口，比如 `8766`，这里也要改成对应的 websocket 地址。

读取当前 session 的 perception 快照：

```bash
uv run robot-agent-perception read \
  --state-root ./.runtime/agent-runtime
```

启动 agent。它会自动发现 `skills/` 下带 `SKILL.md` 的 project skills，并把它们写入当前 session：

```bash
uv run robot-agent start \
  --state-root ./.runtime/agent-runtime
```

如果要启用真实网页搜索和真实飞书发送，在 `.ENV` 里补这些配置：

```bash
TAVILY_API_KEY=...
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_NOTIFY_RECEIVE_ID=...
FEISHU_NOTIFY_RECEIVE_ID_TYPE=chat_id
```

其中 `FEISHU_NOTIFY_RECEIVE_ID_TYPE` 默认为 `chat_id`。

手动发一轮 agent 请求：

```bash
uv run robot-agent chat \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent \
  --text "开始跟踪最开始出现的穿黑衣服的人。"
```

本地开发调试也可以直接启动 REPL：

先安装 TUI 依赖：

```bash
cd terminal
npm install
```

然后启动：

```bash
uv run robot-agent repl \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent
```

`robot-agent repl` 现在会启动基于 `@mariozechner/pi-tui` 的 terminal UI，而不是原来的 `input()` 循环。
`repl` 不再需要传 `--skill`；它会直接使用 `skills/` 下自动发现的 project skills。

在 TUI 内部可用命令：

- `/help`：查看命令
- `/status`：查看当前会话和启用技能
- `/quit` 或 `/q`：退出

注入一条事件 turn，让 Pi 自己决定是否调用通知类 skill：

```bash
uv run robot-agent event \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent \
  --event-type charging_completed \
  --text "机器人底座充电已完成，请根据当前上下文决定是否通知飞书。"
```

单次 deterministic `track`：

```bash
uv run robot-agent tracking-track \
  --session-id <session-id> \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent \
  --text "继续跟踪"
```

这条 `tracking-track` 路径直接调用 `backend.tracking`，不经过 agent runner。

如果只想直接启动底层 tracking loop：

```bash
uv run robot-agent-tracking-loop \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent \
  --interval-seconds 3 \
  --recovery-interval-seconds 1
```


如果只想单独手动启动 viewer websocket：

```bash
uv run robot-agent-tracking-viewer-stream \
  --state-root ./.runtime/agent-runtime \
  --host 127.0.0.1 \
  --port 8765
```

## 当前测试方式

以前那种把 init 一起塞进 stack 的方式不再是推荐测试路径。

现在推荐两种测试方式：

1. 手工联调

```bash
uv run robot-agent-tracking-stack \
  --source backend/tests/fixtures/demo_video.mp4 \
  --state-root ./.runtime/agent-runtime \
  --output-dir ./.runtime/tracking-perception \
  --artifacts-root ./.runtime/pi-agent \
  --device cpu \
  --tracker bytetrack.yaml \
  --realtime-playback
```

然后在另一个终端发 init：

```bash
uv run robot-agent chat \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent \
  --text "开始跟踪穿黑衣服的人。"
```

需要单步测 `track` 时：

```bash
uv run robot-agent tracking-track \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent \
  --text "继续跟踪"
```

2. 自动化端到端 + 延迟报告

```bash
uv run robot-agent-tracking-e2e \
  --demo-video backend/tests/fixtures/demo_video.mp4 \
  --run-root ./.runtime/demo-e2e \
  --device cpu \
  --tracker bytetrack.yaml
```

这个命令会同时检查：
- 端到端效果
- init 单步延迟
- deterministic track 单步延迟
- 模型耗时、非模型开销、async memory rewrite 完成耗时

## 目录

- `agent/`: agent runner、Pi 协议和会话状态视图
- `backend/`: perception、业务编排、持久化和 chat CLI
  - `tracking/`: tracking backend 入口与 loop
- `viewer/`: tracking viewer 前端项目和 websocket stream
- `scripts/`: 仓库级兼容壳
  - `run_tracking_perception.py`: 感知入口
  - `run_tracking_viewer_stream.py`: viewer stream 兼容入口
  - `run_tracking_frontend.sh`: viewer 前端入口
  - `run_tracking_stack.sh`: 兼容性启动壳
- `skills/tracking/`: 只保留目标选择 skill 文档面
- `skills/web_search/`: 网页搜索 skill
- `skills/feishu/`: 飞书通知 skill
- `docs/Tracking Agent 接口.pdf`: 当前接口说明
