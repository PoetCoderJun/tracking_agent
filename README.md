# Tracking Agent

## 安装依赖

```bash
# Python 依赖
uv sync --python 3.9

# 前端依赖
cd frontend && npm install && cd ..

# 配置 API Key
echo "DASHSCOPE_API_KEY=your_key" > .ENV
```

## 启动

```bash
./scripts/server_start.sh
```

访问 http://localhost:8001

## 看日志

```bash
./scripts/server_watch.sh
```

或直接用 tail：

```bash
tail -F runtime/server/logs/combined.log
```

## 关闭

```bash
./scripts/server_stop.sh
```

## 本地 Mock Robot 请求

如果你想在本地模拟 robot 端发送请求来测试 backend，可以使用以下几种方式：

### 1. 使用示例 WebSocket 客户端

```bash
python scaffold/cli/example_robot_websocket_client.py \
  --backend-base-url http://127.0.0.1:8001 \
  --session-id test_session_001 \
  --image ./frame.jpg \
  --text "跟踪穿黑衣服的人" \
  --detections-json '[{"track_id":12,"bbox":[120,80,260,420],"score":0.95},{"track_id":15,"bbox":[300,90,430,410],"score":0.92}]'
```

### 2. 使用最小化 Socket.IO 示例

```bash
python scaffold/cli/minimal_robot_agent_socketio_example.py
```

注意：修改文件中的 `BASE_URL` 为你实际的 backend 地址。

### 3. 使用最小化 WebSocket 示例

```bash
python scaffold/cli/minimal_robot_agent_ws_example.py
```

注意：修改文件中的 `WS_URL` 为你实际的 backend 地址。

### 4. 使用循环 Mock 客户端（模拟多帧跟踪）

```bash
python scaffold/cli/mock_robot_agent_socketio_loop_example.py
```

这个示例会：
- 发送首帧请求（带初始指令，如"请跟踪穿黑衣服的人"）
- 每隔 3 秒发送后续帧（文本为"继续跟踪"）
- 总共发送 5 帧

注意：修改文件中的 `BASE_URL`、`IMAGE_PATH`、`SESSION_ID` 等参数。

### Mock 请求数据格式

```json
{
  "request_id": "req_1234567890",
  "session_id": "sess_demo_001",
  "function": "tracking",
  "frame_id": "frame_000001",
  "timestamp_ms": 1234567890000,
  "device_id": "robot_01",
  "image_base64": "/9j/4AAQ...",
  "detections": [
    {"track_id": 12, "bbox": [120, 80, 260, 420], "score": 0.95},
    {"track_id": 15, "bbox": [300, 90, 430, 410], "score": 0.92}
  ],
  "text": "跟踪穿黑衣服的人"
}
```

字段说明：
- `request_id`: 请求唯一标识
- `session_id`: 会话 ID，相同 session 会共享上下文
- `function`: 功能类型，`tracking` 或 `chat`
- `frame_id`: 帧 ID
- `timestamp_ms`: 时间戳（毫秒）
- `device_id`: 设备 ID
- `image_base64`: Base64 编码的图像数据
- `detections`: 检测结果数组，每个元素包含 `track_id`（跟踪ID）、`bbox`（边界框 `[x1,y1,x2,y2]`）、`score`（置信度）
- `text`: 自然语言指令

## 使用视频文件或摄像头测试

如果你需要使用 MP4 视频文件或本地摄像头进行端到端测试，可以使用内置的 `tracking-robot-stream` 命令：

### 视频文件测试

```bash
uv run tracking-robot-stream \
  --source test_data/demo_video.mp4 \
  --text "跟踪穿黑衣服的人" \
  --device cpu \
  --tracker bytetrack.yaml \
  --session-id test_session_001
```

### 摄像头测试

```bash
uv run tracking-robot-stream \
  --source 0 \
  --text "跟踪穿黑衣服的人" \
  --device cpu \
  --tracker bytetrack.yaml
```

### 常用参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--source` | 视频文件路径或摄像头索引（如 `0`） | 必填 |
| `--session-id` | 会话 ID，相同 session 会共享上下文 | 自动生成 |
| `--device-id` | 设备标识 | `robot_01` |
| `--text` | 首帧的初始化指令文本 | 空 |
| `--ongoing-text` | 后续帧的默认文本 | `持续跟踪` |
| `--interval-seconds` | 发送帧的时间间隔（秒） | `3.0` |
| `--backend-base-url` | Backend 地址 | `http://127.0.0.1:8001` |
| `--backend-protocol` | 传输协议 | `socketio-agent` |
| `--model` | YOLO 模型权重文件 | `yolov8m.pt` |
| `--device` | 推理设备（`cpu`、`mps`、`0` 等） | 自动选择 |
| `--tracker` | 跟踪器配置（如 `bytetrack.yaml`） | 无 |
| `--conf` | 检测置信度阈值 | `0.25` |
| `--vid-stride` | 视频帧采样步长 | `1` |
| `--max-events` | 最大发送事件数 | 无限制 |

### 输出目录

运行后会在 `./runtime/robot-run/{session_id}/` 目录下生成：
- `frames/frame_xxxxxx.jpg` - 采样的视频帧图像
- `events.jsonl` - 发送的事件记录
