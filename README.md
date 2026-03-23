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

## 本地调试方式

```Bash
# 先进入仓库根目录：

cd /path/to/tracking_agent

# 终端 1，启动 backend：

uv run tracking-backend --host 0.0.0.0 --port 8001
# 终端 2，启动 host agent：

uv run tracking-host-agent \
  --backend-base-url http://127.0.0.1:8001
  
# 终端 3，启动前端开发服务器：

cd frontend
export VITE_BACKEND_PROXY_TARGET=http://127.0.0.1:8001
npm run dev -- --host 0.0.0.0 --port 5173
cd ..

# 终端 4，发送一段测试视频
uv run tracking-robot-stream \
  --source test_data/0045.mp4 \
  --text "跟踪穿黑衣服的人" \
  --device cpu \
  --tracker bytetrack.yaml
# 终端 4，如果是本机摄像头：

uv run tracking-robot-stream \
  --source 0 \
  --text "跟踪穿黑衣服的人" \
  --device cpu \
  --tracker bytetrack.yaml
```


注意：

tracking-host-agent 默认会处理所有 session；只有你显式传 --session-id <value> 时，才会只处理单个 session
如果你希望某个 robot stream 固定复用同一个会话，可以显式给 tracking-robot-stream --session-id <value>
服务器没有 GPU 时，tracking-robot-stream 用 --device cpu
前端开发服务器可用 VITE_BACKEND_PROXY_TARGET 和 VITE_BACKEND_PROXY_WS_TARGET 改代理地址
tracking-host-agent --backend-base-url 和 tracking-robot-stream --backend-base-url 都可以直接填写服务器 IP 或域名，例如 10.0.0.8:8001

## 服务端启动方式

```bash
./scripts/server_start.sh
./scripts/server_watch.sh
./scripts/server_stop.sh
```

## 本地 Mock Robot 请求

如果你想在本地模拟 robot 端发送请求来测试 backend，可以用


```bash
python scaffold/cli/mock_robot_agent_socketio_loop_example.py
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
