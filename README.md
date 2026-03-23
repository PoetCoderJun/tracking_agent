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
