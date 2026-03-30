# Robot Agent Runtime

这是一个运行在 robot / Pi 侧的 multi-skills agent runtime。

- `backend/` 是通用 runtime、状态管理和 `robot-agent chat`
- `skills/` 是可插拔 skill
- `scripts/` 是流程性脚本，用来把 perception、轮询、viewer 这些进程跑起来
- `skills/tracking/` 是当前主力 skill
- `skills/speech/` 是已安装的 TTS skill

## 推荐启动

常规 tracking 场景：

1. 先起 perception，默认直接读电脑摄像头。
2. 需要持续 tracking 时，再起 tracking runtime loop。
3. 需要多技能对话时，用 `robot-agent start` 绑定当前 session 的可用 skills。

一把启动 tracking 的 perception 和 tracking runtime：

```bash
uv run robot-agent-tracking-stack \
  --state-root ./.runtime/agent-runtime \
  --output-dir ./.runtime/tracking-perception \
  --artifacts-root ./.runtime/pi-agent \
  --device cpu \
  --tracker bytetrack.yaml \
  --interval-seconds 3
```

如果要在第一帧准备好后自动发送一条初始化 tracking 指令：

```bash
uv run robot-agent-tracking-stack \
  --source backend/tests/fixtures/demo_video.mp4 \
  --state-root ./.runtime/agent-runtime \
  --output-dir ./.runtime/tracking-perception \
  --artifacts-root ./.runtime/pi-agent \
  --device cpu \
  --tracker bytetrack.yaml \
  --interval-seconds 3 \
  --realtime-playback \
  --init-text "开始跟踪穿黑衣服的人"
```

再单独启动 viewer 前端：

```bash
cd skills/tracking/viewer
npm install
VITE_TRACKING_VIEWER_WS_URL=ws://127.0.0.1:8765 npm run dev
```

只要 tracking runtime loop 正在运行，就会同时提供 `ws://127.0.0.1:8765` 的 viewer stream。
如果指定的 viewer IP 无法绑定，tracking runtime 会跳过推流，但不会退出。

## 常用手工命令

只启动 perception：

```bash
uv run robot-agent-tracking-perception \
  --state-root ./.runtime/agent-runtime \
  --output-dir ./.runtime/tracking-perception \
  --device cpu \
  --tracker bytetrack.yaml \
  --interval-seconds 3
```

测试模式下如果要回放文件，再显式指定 `--source`：

```bash
uv run robot-agent-tracking-perception \
  --source backend/tests/fixtures/demo_video.mp4 \
  --state-root ./.runtime/agent-runtime \
  --output-dir ./.runtime/tracking-perception \
  --device cpu \
  --tracker bytetrack.yaml \
  --interval-seconds 3 \
  --realtime-playback
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

启动自动轮询：

```bash
uv run robot-agent-tracking-loop \
  --state-root ./.runtime/agent-runtime \
  --artifacts-root ./.runtime/pi-agent \
  --interval-seconds 3 \
  --viewer-host 127.0.0.1 \
  --viewer-port 8765
```

如果只想启用 TTS：

```bash
uv run robot-agent start \
  --state-root ./.runtime/agent-runtime \
  --skill speech
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
- `skills/tracking/`: tracking skill 与单轮 helper
- `skills/speech/`: speech skill
- `docs/agent-architecture.md`: 补充说明
