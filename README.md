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
- Robot 只上传原始帧、候选 detections 和文本；是否调用 init / track 由统一对话 Agent 决定
- 文件回放模式下，会按视频时间每 `3` 秒取一帧；每次等 backend 返回后立刻发送下一条，不再额外 `sleep`；首帧文本默认作为初始化描述，后续事件默认发送 `持续跟踪`
- Robot 默认会把数据发到 `http://127.0.0.1:8001/api/v1/robot/ingest`
- 如果需要复用同一个会话，显式传 `--session-id <your_session_id>`

## 页面内容

- 当前画面
- 候选框和选中框
- 当前 Agent 回复
- 当前 memory
- 最近几轮结果时间线
- 展示页不提供前端指令输入，Agent 由 robot ingest 自动触发
