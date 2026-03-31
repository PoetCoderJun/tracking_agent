# Robot Agent Runtime

这是一个运行在 robot / Pi 侧的 multi-skills agent runtime。

- `backend/` 是通用 runtime、状态管理和 `robot-agent chat`
- `backend/perception/cli.py` 是独立感知服务的查询入口，供 Runtime / Pi 通过 CLI 读取
- `skills/` 是可插拔 skill
- `scripts/` 是流程性脚本，用来把 perception、轮询、viewer 这些进程跑起来
- `skills/tracking/` 是当前主力 skill
- `skills/speech/` 是已安装的 TTS skill

## 推荐启动

当前推荐把 tracking 系统拆成 4 个独立进程：

1. perception：持续写入检测与帧
2. backend：viewer websocket 后端
3. agent：初始化目标、恢复态请求、并打印 agent 聊天日志
4. frontend：viewer 前端

`scripts/run_tracking_stack.sh` 现在只是一个薄壳：
- 同时启动上面 4 个进程
- 为它们绑定同一个 `session_id`
- 给每路日志加前缀并打印

推荐直接这样启动：

```bash
bash scripts/run_tracking_stack.sh \
  --source backend/tests/fixtures/demo_video.mp4 \
  --state-root ./.runtime/agent-runtime \
  --output-dir ./.runtime/tracking-perception \
  --artifacts-root ./.runtime/pi-agent \
  --device cpu \
  --tracker bytetrack.yaml \
  --realtime-playback \
  --init-text "开始跟踪穿黑衣服的人"
```

启动后：
- 后端 websocket 默认在 `ws://127.0.0.1:8765`
- agent 日志会直接打印到终端，包括新增的聊天记录
- stack 默认不启动前端，避免把 viewer 强耦合进主流程

如果你更看重可控性，也可以把 4 个进程分开启动。


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

只启动 backend websocket：

```bash
uv run robot-agent-tracking-backend \
  --state-root ./.runtime/agent-runtime \
  --host 127.0.0.1 \
  --port 8765
```

只启动 agent：

```bash
uv run robot-agent-tracking-agent \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent \
  --env-file .ENV \
  --init-text "开始跟踪穿黑衣服的人"
```

这个入口会：
- 等待 perception 写出首帧
- 自动发起初始化 chat
- 后续运行 tracking loop
- 持续打印 agent 聊天日志

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

启动 agent，并指定当前 session 启用哪些 skills：

```bash
uv run robot-agent start \
  --state-root ./.runtime/agent-runtime \
  --skill tracking \
  --skill speech
```

手动发一轮 agent 请求：

```bash
uv run robot-agent chat \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent \
  --text "开始跟踪最开始出现的穿黑衣服的人。"
```

继续跟踪：

```bash
uv run robot-agent chat --state-root ./.runtime/agent-runtime --text "继续跟踪"
```

如果只想直接启动底层 tracking loop：

```bash
uv run robot-agent-tracking-loop \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent \
  --interval-seconds 3 \
  --recovery-interval-seconds 1 \
  --viewer-host 127.0.0.1 \
  --viewer-port 8765
```


如果只想单独手动启动 viewer websocket：

```bash
uv run robot-agent-tracking-viewer-stream \
  --state-root ./.runtime/agent-runtime \
  --host 127.0.0.1 \
  --port 8765
```

## 目录

- `backend/`: 通用 runtime
- `scripts/`: 仓库级流程脚本
  - `run_tracking_perception.py`: 感知入口
  - `run_tracking_backend.py`: viewer websocket 后端入口
  - `run_tracking_agent.py`: tracking agent 入口，包含 init + loop + 聊天日志打印
  - `run_tracking_frontend.sh`: viewer 前端入口
  - `run_tracking_stack.sh`: 纯启动壳，同时拉起 perception/backend/agent/frontend
- `skills/tracking/`: tracking skill 与单轮 helper
- `skills/speech/`: speech skill
- `docs/agent-architecture.md`: 补充说明
- `docs/agent-runtime-report.md`: 结构化设计与调用报告，覆盖 Agent/Pi runner/context/VLM/multi-skills/perception
