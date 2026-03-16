# Tracking Agent

## 安装

```bash
uv sync
cd frontend && npm install
```

如果要运行外部 host agent，仓库根目录需要 `.ENV`，至少包含：

```bash
DASHSCOPE_API_KEY=...
```

## 启动

推荐固定同一个 `session-id` 跑完整闭环，否则 `tracking-robot-stream` 会自动生成新 session，`tracking-host-agent --session-id default` 将看不到那一轮数据。

```bash
uv run tracking-backend
```

```bash
uv run tracking-host-agent --session-id default
```

```bash
cd frontend && npm run dev
```

```bash
uv run tracking-robot-stream --session-id default --source test_data/0045.mp4 --text "跟踪穿黑衣服的人" --device mps --tracker bytetrack.yaml
```

摄像头输入：

```bash
uv run tracking-robot-stream --session-id default --source 0 --text "跟踪穿黑衣服的人" --device mps --tracker bytetrack.yaml
```

如果你不想固定 `session-id`，也可以让 host agent 自动扫描所有 session：

```bash
uv run tracking-host-agent
```

页面地址：

```bash
http://127.0.0.1:5173
```

## 边界

- Agent: 只通过 `skills/vision-tracking-skill/` 暴露的 skill tools 推进会话。目标绑定、memory 更新、澄清提问都由 Agent 决定。
- Backend: 只接收 Robot 事件、保存会话状态、提供 `agent-context` 给 Agent、接收 `agent-result`。Backend 不解释 Robot 文本，不做本地意图识别，不做本地 agent 编排。
- Frontend: 只读展示 Backend 当前状态、历史结果、会话日志和画面。
- Robot: 只发送图片、文本和 bounding box/detection 数据，不参与 memory、target 选择或对话决策。

## 默认值

- Backend: `127.0.0.1:8001`，状态目录 `./runtime/backend`
- Host agent: 通过 websocket 订阅 backend 的 session 事件，自动为新帧执行 `init / track / reply`；默认断线重连间隔 `2` 秒
- Robot: 输出目录 `./runtime/robot-run`，默认每次运行自动生成新的 session，device `robot_01`
- Robot 默认检测模型是 `YOLO11m Person`，底层权重为 `yolo11m.pt`，并只推理 `person` 类别
- Robot 默认每 `3` 秒发送一次当前帧事件到 backend
- Robot 只上传原始帧、候选 detections 和文本；backend 不会把这些文本解释成 `target_description`，也不会在 ingest 后自动调用本地 agent，只会等待外部 PI Agent 把同一帧的 `/agent-result` 回写后再回复 robot
- 如果需要本仓库内的自动闭环，额外启动 `uv run tracking-host-agent --session-id <session_id>`；它会调用 `skills/vision-tracking-skill/scripts/pi_backend_bridge.py`
- 文件回放模式下，会按视频时间每 `3` 秒取一帧；robot 在收到 backend 对上一帧的回复后，才会继续发送下一条，不再额外 `sleep`；首帧文本默认作为初始化描述，后续事件默认发送 `持续跟踪`
- Robot 默认会通过 websocket 把数据发到 `ws://127.0.0.1:8001/ws/robot-ingest`
- 如果需要复用同一个会话，显式传 `--session-id <your_session_id>`
- 如果 `tracking-host-agent` 指定了 `--session-id default`，那 `tracking-robot-stream` 也必须传同一个 `--session-id default`；否则 host agent 只会订阅并处理 `default`，robot 实际发到自动生成的新 session，表现就是“没有报错，但完全不推进”
- Backend 默认最多等待外部 agent `300` 秒，可用 `uv run tracking-backend --external-agent-wait-seconds 0` 关闭等待
- Robot 默认等待 backend websocket 应答的超时是 `310` 秒，可用 `--backend-timeout-seconds` 调整；如果显式传 HTTP URL，也会兼容回退到旧的 `POST /api/v1/robot/ingest`

## PI Agent 对接

- 工具契约：`skills/vision-tracking-skill/references/pi-agent-tools.json`
- Host agent 配置：`skills/vision-tracking-skill/references/pi-host-agent-config.json`
- Skill adapter：`skills/vision-tracking-skill/scripts/pi_agent_adapter.py`
- Backend bridge：`skills/vision-tracking-skill/scripts/pi_backend_bridge.py`
- 本地常驻 host agent：`scaffold/cli/run_host_agent.py`
- backend 只提供 `agent-context` / `agent-result` 契约；仓库内不再提供本地回合编排器
- 查看工具定义：

```bash
python skills/vision-tracking-skill/scripts/pi_agent_adapter.py describe
```

- 执行某个工具时，PI Agent 先读取 `/api/v1/sessions/{session_id}/agent-context`，再把该 JSON 作为 `--context-file` 输入给 adapter，最后把 adapter 输出回写到 `/api/v1/sessions/{session_id}/agent-result`
- 如果你想在本仓库内自动处理每一帧，直接启动：

```bash
uv run tracking-host-agent --session-id default
```

- 常见卡住原因：host agent 和 robot 的 `session-id` 不一致。例如 host agent 监听 `default`，但 robot 没传 `--session-id`，这时 robot 会发到类似 `session_20260316T034923567075Z` 的新 session，backend 会等待这个新 session 的 `/agent-result`，而 host agent 仍只会处理 `default`

- 如果你只想走通某个固定工具，也可以直接用 bridge：

```bash
python skills/vision-tracking-skill/scripts/pi_backend_bridge.py \
  --session-id <session_id> \
  --tool track
```

## 页面内容

- 当前画面
- 候选框和选中框
- 当前 Agent 回复
- 当前 memory
- 最近几轮结果时间线
- 最近几轮对话日志
- 展示页不提供前端指令输入，也不提供会话控制；PI Agent 应从 `/api/v1/sessions/{session_id}/agent-context` 读取上下文，并将结果回写到 `/api/v1/sessions/{session_id}/agent-result`
