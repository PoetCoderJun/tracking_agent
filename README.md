# Robot Agent Runtime

这是一个运行在 robot / Pi 侧的 chat-first embodied agent kernel。

- `backend/` 是 perception、runner、状态管理和 `robot-agent chat`
- `backend/perception/cli.py` 是独立感知服务的查询入口，供 Runtime / Pi 通过 CLI 读取
- `skills/` 提供 capability 实现，当前重点是 tracking 和 speech
- `scripts/` 是流程性脚本，用来把 perception、轮询、viewer 这些进程跑起来
- `skills/tracking/` 是当前主力 skill
- `skills/speech/` 是已安装的 TTS skill

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
- websocket 默认在 `ws://127.0.0.1:8765`
- tracking loop 会持续读取 perception 并在需要时触发 runner
- stack 默认不启动前端，避免把 viewer 强耦合进主流程

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
- `backend/`: perception + runner + session state
- `scripts/`: 仓库级流程脚本
  - `run_tracking_perception.py`: 感知入口
  - `run_tracking_viewer_stream.py`: viewer websocket 后端入口
  - `run_tracking_frontend.sh`: viewer 前端入口
  - `run_tracking_stack.sh`: 兼容性启动壳
- `apps/tracking-viewer/`: tracking viewer 前端项目
- `skills/tracking/`: tracking skill 与单轮 helper
- `skills/speech/`: speech skill
- `docs/agent-architecture.md`: 补充说明
- `docs/agent-runtime-report.md`: 结构化设计与调用报告，覆盖 Agent/Pi runner/context/VLM/multi-skills/perception
