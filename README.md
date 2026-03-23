# Tracking Agent

一个最小可运行的人体跟踪 Agent 工程，包含 3 个部分：

- Backend：接收机器人帧、保存会话状态、提供 API 和 WebSocket
- Host Agent：读取 backend 上下文，调用 `skills/vision-tracking-skill/`，再把结果回写给 backend
- Frontend：展示当前画面、检测框、会话结果和历史记录

## 1. 安装指南

### 环境要求

- Python `3.9.x`
- Node.js `20.x`
- `uv`

### 本地安装

```bash
git clone <your-repo-url>
cd tracking_agent
uv python install 3.9
uv sync --python 3.9
cd frontend
npm install
cd ..
```

### `.ENV`

如果你要运行 `tracking-host-agent`，仓库根目录需要 `.ENV`：

```bash
DASHSCOPE_API_KEY=your_api_key
```

可选项：

```bash
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.5-plus
DASHSCOPE_SUB_MODEL=qwen3.5-flash
DASHSCOPE_CHAT_MODEL=qwen3.5-flash
```

## 2. 服务器安装指南

下面是一台全新 Ubuntu 机器的最小安装步骤。

### 安装系统依赖

```bash
sudo apt update
sudo apt install -y git curl ca-certificates build-essential
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv python install 3.9
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

### 拉代码并安装依赖

```bash
git clone <your-repo-url> /srv/tracking_agent
cd /srv/tracking_agent
uv sync --python 3.9
cd frontend
npm install
cd ..
```

### 配置 `.ENV`

```bash
cd /srv/tracking_agent
cat > .ENV <<'EOF'
DASHSCOPE_API_KEY=your_api_key
EOF
```

## 3. 如何让服务器运转起来

### 开发模式：先用 3 个终端跑通

终端 1，启动 backend：

```bash
cd /srv/tracking_agent
uv run tracking-backend --host 0.0.0.0 --port 8001
```

终端 2，启动 host agent：

```bash
cd /srv/tracking_agent
uv run tracking-host-agent \
  --backend-base-url http://127.0.0.1:8001
```

终端 3，启动前端开发服务器：

```bash
cd /srv/tracking_agent/frontend
export VITE_BACKEND_PROXY_TARGET=http://127.0.0.1:8001
npm run dev -- --host 0.0.0.0 --port 5173
```

访问地址：

```text
http://<server-ip>:5173
```

健康检查：

```bash
curl http://127.0.0.1:8001/healthz
```

### 发送一段测试视频

```bash
cd /srv/tracking_agent
uv run tracking-robot-stream \
  --source test_data/0045.mp4 \
  --text "跟踪穿黑衣服的人" \
  --device cpu \
  --tracker bytetrack.yaml
```

如果是本机摄像头：

```bash
cd /srv/tracking_agent
uv run tracking-robot-stream \
  --source 0 \
  --text "跟踪穿黑衣服的人" \
  --device cpu \
  --tracker bytetrack.yaml
```

注意：

- `tracking-host-agent` 默认会处理所有 session；只有你显式传 `--session-id <value>` 时，才会只处理单个 session
- 如果你希望某个 robot stream 固定复用同一个会话，可以显式给 `tracking-robot-stream --session-id <value>`
- 服务器没有 GPU 时，`tracking-robot-stream` 用 `--device cpu`
- 前端开发服务器可用 `VITE_BACKEND_PROXY_TARGET` 和 `VITE_BACKEND_PROXY_WS_TARGET` 改代理地址
- `tracking-host-agent --backend-base-url` 和 `tracking-robot-stream --backend-base-url` 都可以直接填写服务器 IP 或域名，例如 `10.0.0.8:8001`

### 生产模式：后端直接托管前端

如果你要在一台服务器上直接部署一个可访问的成品，推荐把前端先 build，再由 backend 直接托管静态文件。这样只需要对外暴露 backend 一个端口。

构建前端：

```bash
cd /srv/tracking_agent/frontend
npm run build
```

启动 backend（同时提供 API、WebSocket、前端页面）：

```bash
cd /srv/tracking_agent
uv run tracking-backend \
  --host 0.0.0.0 \
  --port 8001 \
  --public-base-url http://<server-ip>:8001 \
  --frontend-dist ./frontend/dist \
  --allow-origin http://<server-ip>:8001
```

启动 host agent：

```bash
cd /srv/tracking_agent
uv run tracking-host-agent \
  --backend-base-url http://127.0.0.1:8001
```

此时访问：

```text
http://<server-ip>:8001
```

### 一键启动 / 一键关闭 / 实时看日志

仓库自带 3 个脚本，默认会把 backend 和 host-agent 的日志统一放到同一个目录：

- `./scripts/server_start.sh`
- `./scripts/server_stop.sh`
- `./scripts/server_watch.sh`

默认日志和 pid 目录：

```text
./runtime/server/logs/
./runtime/server/pids/
```

其中：

- backend 日志：`./runtime/server/logs/backend.log`
- agent 日志：`./runtime/server/logs/host-agent.log`
- 合并日志：`./runtime/server/logs/combined.log`

一键启动：

```bash
cd /srv/tracking_agent
./scripts/server_start.sh
```

一键关闭：

```bash
cd /srv/tracking_agent
./scripts/server_stop.sh
```

实时看合并日志：

```bash
cd /srv/tracking_agent
./scripts/server_watch.sh
```

也可以直接：

```bash
tail -F /srv/tracking_agent/runtime/server/logs/combined.log
```

脚本默认行为：

- 启动前会自动执行 `frontend/npm run build`
- backend 对外监听 `0.0.0.0:8001`
- backend 内部回环地址默认是 `http://127.0.0.1:8001`
- host-agent 默认处理所有 session

如需覆盖默认值，可以在执行前设置这些环境变量：

```bash
TRACKING_SERVER_HOST=0.0.0.0
TRACKING_SERVER_PORT=8001
# 可选：只让 host-agent 处理某个固定 session
TRACKING_SERVER_SESSION_ID=
TRACKING_SERVER_PUBLIC_BASE_URL=http://<server-ip>:8001
TRACKING_SERVER_ALLOW_ORIGIN=http://<server-ip>:8001
TRACKING_SERVER_INTERNAL_BACKEND_URL=http://127.0.0.1:8001
TRACKING_SERVER_RUNTIME_DIR=/srv/tracking_agent/runtime/server
TRACKING_SERVER_ENV_FILE=/srv/tracking_agent/.ENV
TRACKING_SERVER_SKIP_FRONTEND_BUILD=1
```

如果前端单独部署在别的域名或端口：

- backend 启动时用 `--public-base-url` 生成可被前端直接访问的绝对资源地址
- frontend 构建前设置 `VITE_BACKEND_BASE_URL=http://<backend-ip>:8001`
- 如需显式指定 WebSocket 地址，再设置 `VITE_BACKEND_WS_BASE_URL=ws://<backend-ip>:8001`
- backend 可用 `--allow-origin http://<frontend-origin>` 只放行指定前端来源

### 需要常驻运行时，用 systemd

把下面 3 个服务文件中的路径和用户名改成你自己的。

`/etc/systemd/system/tracking-backend.service`

```ini
[Unit]
Description=Tracking Agent Backend
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/srv/tracking_agent
Environment=PATH=/home/ubuntu/.local/bin:/usr/bin:/bin
ExecStart=/home/ubuntu/.local/bin/uv run tracking-backend --host 0.0.0.0 --port 8001 --public-base-url http://<server-ip>:8001 --frontend-dist ./frontend/dist --allow-origin http://<server-ip>:8001
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/tracking-host-agent.service`

```ini
[Unit]
Description=Tracking Host Agent
After=network.target tracking-backend.service

[Service]
User=ubuntu
WorkingDirectory=/srv/tracking_agent
Environment=PATH=/home/ubuntu/.local/bin:/usr/bin:/bin
ExecStart=/home/ubuntu/.local/bin/uv run tracking-host-agent --backend-base-url http://127.0.0.1:8001
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

加载并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tracking-backend
sudo systemctl enable --now tracking-host-agent
```

查看状态：

```bash
sudo systemctl status tracking-backend
sudo systemctl status tracking-host-agent
```

查看日志：

```bash
journalctl -u tracking-backend -f
journalctl -u tracking-host-agent -f
```
