# Tracking Agent

## 安装

```bash
uv sync
cd frontend && npm install
```

仓库根目录需要 `.ENV`，至少包含：

```bash
DASHSCOPE_API_KEY=...
```

## 启动

```bash
uv run tracking-backend
```

```bash
cd frontend && npm run dev
```

```bash
uv run tracking-robot-stream --source test_data/0045.mp4 --text "跟踪穿黑衣服的人"
```

摄像头输入：

```bash
uv run tracking-robot-stream --source 0 --text "跟踪穿黑衣服的人"
```

页面地址：

```bash
http://127.0.0.1:5173
```

## 默认值

- Backend: `127.0.0.1:8001`，状态目录 `./runtime/backend`
- Robot: 输出目录 `./runtime/robot-run`，默认每次运行自动生成新的 session，device `robot_01`
- Robot 默认每 `3` 秒发送一次当前帧事件到 backend
- Robot 只上传原始帧、候选 detections 和文本；如果 `.ENV` 里有可用模型配置，backend 会在 ingest 后同步调用 agent；如果没有自动 agent，backend 会等待外部 PI Agent 把同一帧的 `/agent-result` 回写后再回复 robot
- 文件回放模式下，会按视频时间每 `3` 秒取一帧；robot 在收到 backend 对上一帧的回复后，才会继续发送下一条，不再额外 `sleep`；首帧文本默认作为初始化描述，后续事件默认发送 `持续跟踪`
- Robot 默认会把数据发到 `http://127.0.0.1:8001/api/v1/robot/ingest`
- 如果需要复用同一个会话，显式传 `--session-id <your_session_id>`
- Backend 默认最多等待外部 agent `300` 秒，可用 `uv run tracking-backend --external-agent-wait-seconds 0` 关闭等待
- Robot 默认 HTTP 等待超时是 `310` 秒，可用 `--backend-timeout-seconds` 调整

## PI Agent 对接

- 工具契约：`skills/vision-tracking-skill/references/pi-agent-tools.json`
- Host agent 配置：`skills/vision-tracking-skill/references/pi-host-agent-config.json`
- Skill adapter：`skills/vision-tracking-skill/scripts/pi_agent_adapter.py`
- Backend bridge：`skills/vision-tracking-skill/scripts/pi_backend_bridge.py`
- Model-driven host turn：`skills/vision-tracking-skill/scripts/pi_host_turn.py`
- 如果 backend 没有配置自动 agent，或者你想手动重放某一轮，再使用下面这些桥接脚本
- 查看工具定义：

```bash
python skills/vision-tracking-skill/scripts/pi_agent_adapter.py describe
```

- 执行某个工具时，PI Agent 先读取 `/api/v1/sessions/{session_id}/agent-context`，再把该 JSON 作为 `--context-file` 输入给 adapter，最后把 adapter 输出回写到 `/api/v1/sessions/{session_id}/agent-result`
- 如果你只想走通最小闭环，可以直接用 bridge：
 
```bash
python skills/vision-tracking-skill/scripts/pi_host_turn.py \
  --session-id <session_id>
```

- 上面这个入口会把 `vision-tracking-skill` 作为一个顶层 skill 运行，并把 `reply/init/track/rewrite_memory` 暴露给模型做 tool calling。
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
- 展示页不提供前端指令输入；PI Agent 应从 `/api/v1/sessions/{session_id}/agent-context` 读取上下文，并将结果回写到 `/api/v1/sessions/{session_id}/agent-result`
