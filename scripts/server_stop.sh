#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RUNTIME_DIR="${TRACKING_SERVER_RUNTIME_DIR:-$ROOT_DIR/runtime/server}"
LOG_DIR="${TRACKING_SERVER_LOG_DIR:-$RUNTIME_DIR/logs}"
PID_DIR="${TRACKING_SERVER_PID_DIR:-$RUNTIME_DIR/pids}"

BACKEND_PID_FILE="$PID_DIR/backend.pid"
HOST_AGENT_PID_FILE="$PID_DIR/host-agent.pid"
COMBINED_LOG="$LOG_DIR/combined.log"

stop_service() {
  local name="$1"
  local pid_file="$2"
  if [[ ! -f "$pid_file" ]]; then
    echo "$name is not running."
    return 0
  fi

  local pid
  pid="$(cat "$pid_file")"
  if [[ -z "$pid" ]]; then
    rm -f "$pid_file"
    echo "$name pid file was empty and has been cleaned."
    return 0
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    echo "$name is already stopped."
    return 0
  fi

  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pid_file"
      echo "$name stopped."
      return 0
    fi
    sleep 1
  done

  kill -9 "$pid" 2>/dev/null || true
  rm -f "$pid_file"
  echo "$name did not exit in time and was force killed."
}

stop_service "host-agent" "$HOST_AGENT_PID_FILE"
stop_service "backend" "$BACKEND_PID_FILE"

mkdir -p "$LOG_DIR"
printf '\n==== %s server_stop ====\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$COMBINED_LOG"
