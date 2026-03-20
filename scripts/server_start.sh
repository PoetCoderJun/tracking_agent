#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Disable proxy for local services
export no_proxy="127.0.0.1,localhost,::1"
export NO_PROXY="127.0.0.1,localhost,::1"

HOST="${TRACKING_SERVER_HOST:-0.0.0.0}"
PORT="${TRACKING_SERVER_PORT:-8001}"
SESSION_ID="${TRACKING_SERVER_SESSION_ID:-default}"
RUNTIME_DIR="${TRACKING_SERVER_RUNTIME_DIR:-$ROOT_DIR/runtime/server}"
LOG_DIR="${TRACKING_SERVER_LOG_DIR:-$RUNTIME_DIR/logs}"
PID_DIR="${TRACKING_SERVER_PID_DIR:-$RUNTIME_DIR/pids}"
FRONTEND_DIR="${TRACKING_SERVER_FRONTEND_DIR:-$ROOT_DIR/frontend}"
FRONTEND_DIST="${TRACKING_SERVER_FRONTEND_DIST:-$FRONTEND_DIR/dist}"
ENV_FILE="${TRACKING_SERVER_ENV_FILE:-$ROOT_DIR/.ENV}"
INTERNAL_BACKEND_URL="${TRACKING_SERVER_INTERNAL_BACKEND_URL:-http://127.0.0.1:${PORT}}"
PUBLIC_BASE_URL="${TRACKING_SERVER_PUBLIC_BASE_URL:-$INTERNAL_BACKEND_URL}"
ALLOW_ORIGIN="${TRACKING_SERVER_ALLOW_ORIGIN:-$PUBLIC_BASE_URL}"
SKIP_FRONTEND_BUILD="${TRACKING_SERVER_SKIP_FRONTEND_BUILD:-0}"
FRONTEND_DEV="${TRACKING_FRONTEND_DEV:-0}"
FRONTEND_PORT="${TRACKING_FRONTEND_PORT:-5173}"

FRONTEND_PID_FILE="$PID_DIR/frontend.pid"
BACKEND_PID_FILE="$PID_DIR/backend.pid"
HOST_AGENT_PID_FILE="$PID_DIR/host-agent.pid"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_LOG="$LOG_DIR/backend.log"
HOST_AGENT_LOG="$LOG_DIR/host-agent.log"
COMBINED_LOG="$LOG_DIR/combined.log"

mkdir -p "$LOG_DIR" "$PID_DIR"

is_running() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi

  local pid
  pid="$(cat "$pid_file")"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

ensure_stopped() {
  local name="$1"
  local pid_file="$2"
  if is_running "$pid_file"; then
    echo "$name is already running (pid $(cat "$pid_file"))."
    echo "Run ./scripts/server_stop.sh first if you want to restart it."
    exit 1
  fi
  rm -f "$pid_file"
}

start_service() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  shift 3

  (
    cd "$ROOT_DIR"
    export PYTHONUNBUFFERED=1
    exec "$@"
  ) > >(
    while IFS= read -r line; do
      timestamp="$(date '+%Y-%m-%dT%H:%M:%S%z')"
      formatted="${timestamp} [${name}] ${line}"
      printf '%s\n' "$formatted" | tee -a "$log_file" >> "$COMBINED_LOG"
    done
  ) 2>&1 &

  local pid=$!
  echo "$pid" > "$pid_file"
}

wait_for_healthz() {
  local url="$1"
  local attempts="${2:-20}"
  local sleep_seconds="${3:-1}"

  for ((i = 0; i < attempts; i += 1)); do
    if curl --silent --fail "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$sleep_seconds"
  done
  return 1
}

ensure_stopped "frontend" "$FRONTEND_PID_FILE"
ensure_stopped "backend" "$BACKEND_PID_FILE"
ensure_stopped "host-agent" "$HOST_AGENT_PID_FILE"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE"
  echo "Create it first, for example by copying your .ENV to that path."
  exit 1
fi

if [[ "$SKIP_FRONTEND_BUILD" != "1" && "$FRONTEND_DEV" != "1" ]]; then
  (
    cd "$FRONTEND_DIR"
    npm run build
  )
fi

if [[ "$FRONTEND_DEV" == "1" ]]; then
  # Disable proxy for frontend dev server
  (
    cd "$FRONTEND_DIR"
    unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
    npm run dev -- --port "$FRONTEND_PORT" --host > >(while IFS= read -r line; do timestamp="$(date '+%Y-%m-%dT%H:%M:%S%z')"; printf '%s\n' "${timestamp} [frontend] ${line}" | tee -a "$FRONTEND_LOG" >> "$COMBINED_LOG"; done) 2>&1 &
    echo $! > "$FRONTEND_PID_FILE"
  )
  echo "Frontend dev server is starting on http://127.0.0.1:$FRONTEND_PORT"
  sleep 3
fi

printf '\n==== %s server_start ====\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$COMBINED_LOG"

if [[ "$FRONTEND_DEV" == "1" ]]; then
  start_service \
    "backend" \
    "$BACKEND_PID_FILE" \
    "$BACKEND_LOG" \
    uv run tracking-backend \
      --host "$HOST" \
      --port "$PORT" \
      --public-base-url "$PUBLIC_BASE_URL" \
      --allow-origin "$ALLOW_ORIGIN"
else
  start_service \
    "backend" \
    "$BACKEND_PID_FILE" \
    "$BACKEND_LOG" \
    uv run tracking-backend \
      --host "$HOST" \
      --port "$PORT" \
      --public-base-url "$PUBLIC_BASE_URL" \
      --frontend-dist "$FRONTEND_DIST" \
      --allow-origin "$ALLOW_ORIGIN"
fi

if ! wait_for_healthz "${INTERNAL_BACKEND_URL}/healthz" 30 1; then
  echo "Backend failed to become healthy. Check $BACKEND_LOG or $COMBINED_LOG."
  exit 1
fi

start_service \
  "host-agent" \
  "$HOST_AGENT_PID_FILE" \
  "$HOST_AGENT_LOG" \
  uv run tracking-host-agent \
    --backend-base-url "$INTERNAL_BACKEND_URL" \
    --session-id "$SESSION_ID" \
    --env-file "$ENV_FILE"

sleep 1

if ! is_running "$HOST_AGENT_PID_FILE"; then
  echo "Host agent exited immediately. Check $HOST_AGENT_LOG or $COMBINED_LOG."
  exit 1
fi

echo "Tracking server is up."
if [[ "$FRONTEND_DEV" == "1" ]]; then
  echo "Frontend dev server: http://127.0.0.1:$FRONTEND_PORT (PID: $(cat "$FRONTEND_PID_FILE"))"
fi
echo "Backend PID: $(cat "$BACKEND_PID_FILE")"
echo "Host agent PID: $(cat "$HOST_AGENT_PID_FILE")"
echo "Logs:"
echo "  $BACKEND_LOG"
echo "  $HOST_AGENT_LOG"
echo "  $COMBINED_LOG"
echo "Watch live logs with:"
echo "  tail -F \"$COMBINED_LOG\""
