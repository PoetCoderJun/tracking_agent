#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_ROOT="./.runtime/agent-runtime"
SOURCE="0"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="5173"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8765"
REALTIME_PLAYBACK="0"
START_FRONTEND="0"
SHUTTING_DOWN="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      SOURCE="$2"
      shift 2
      ;;
    --state-root)
      STATE_ROOT="$2"
      shift 2
      ;;
    --frontend-host)
      FRONTEND_HOST="$2"
      shift 2
      ;;
    --frontend-port)
      FRONTEND_PORT="$2"
      shift 2
      ;;
    --start-frontend)
      START_FRONTEND="1"
      shift
      ;;
    --backend-host)
      BACKEND_HOST="$2"
      shift 2
      ;;
    --backend-port)
      BACKEND_PORT="$2"
      shift 2
      ;;
    --realtime-playback)
      REALTIME_PLAYBACK="1"
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

declare -a PIDS=()

ensure_command() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Missing required command: ${name}" >&2
    exit 1
  fi
}

ensure_port_free() {
  local host="$1"
  local port="$2"
  local service_name="$3"
  local listeners
  listeners="$(lsof -nP -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "${listeners}" ]]; then
    return 0
  fi
  echo "[stack] ${service_name} port ${host}:${port} is already in use." >&2
  echo "${listeners}" >&2
  exit 1
}

cleanup() {
  if [[ "${SHUTTING_DOWN}" == "1" ]]; then
    return 0
  fi
  SHUTTING_DOWN="1"
  for pid in "${PIDS[@]:-}"; do
    kill_tree "${pid}"
  done
  wait || true
}

prefix_stream() {
  local default_name="$1"
  local line
  while IFS= read -r line || [[ -n "${line}" ]]; do
    printf '[%s] %s\n' "${default_name}" "${line}"
  done
}

kill_tree() {
  local pid="$1"
  local children
  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" >/dev/null 2>&1; then
    return 0
  fi
  children="$(pgrep -P "${pid}" 2>/dev/null || true)"
  if [[ -n "${children}" ]]; then
    while IFS= read -r child; do
      if [[ -n "${child}" ]]; then
        kill_tree "${child}"
      fi
    done <<< "${children}"
  fi
  kill -TERM "${pid}" >/dev/null 2>&1 || true
  sleep 0.2
  kill -0 "${pid}" >/dev/null 2>&1 || return 0
  kill -KILL "${pid}" >/dev/null 2>&1 || true
}

handle_interrupt() {
  trap - EXIT INT TERM
  cleanup
  exit 130
}

handle_term() {
  trap - EXIT INT TERM
  cleanup
  exit 143
}

trap cleanup EXIT
trap handle_interrupt INT
trap handle_term TERM

run_component() {
  local name="$1"
  shift
  (
    printf '[%s] command:' "${name}"
    for arg in "$@"; do
      printf ' %s' "${arg}"
    done
    printf '\n'
    "$@" 2>&1 | prefix_stream "${name}"
  ) &
  PIDS+=("$!")
}

ensure_command uv
ensure_port_free "${BACKEND_HOST}" "${BACKEND_PORT}" "backend websocket"
if [[ "${START_FRONTEND}" == "1" ]]; then
  ensure_command npm
  ensure_port_free "${FRONTEND_HOST}" "${FRONTEND_PORT}" "frontend"
fi

PERCEPTION_CMD=(uv run python -m scripts.run_perception
  --source "${SOURCE}"
  --state-root "${STATE_ROOT}"
  --interval-seconds "1.0"
)
if [[ "${REALTIME_PLAYBACK}" == "1" ]]; then
  PERCEPTION_CMD+=(--realtime-playback)
fi

BACKEND_CMD=(uv run python -m viewer.stream
  --state-root "${STATE_ROOT}"
  --host "${BACKEND_HOST}"
  --port "${BACKEND_PORT}"
)

run_component perception "${PERCEPTION_CMD[@]}"
run_component backend "${BACKEND_CMD[@]}"

if [[ "${START_FRONTEND}" == "1" ]]; then
  FRONTEND_CMD=(bash "${ROOT_DIR}/scripts/run_tracking_frontend.sh"
    --host "${FRONTEND_HOST}"
    --port "${FRONTEND_PORT}"
    --ws-url "ws://${BACKEND_HOST}:${BACKEND_PORT}"
  )
  run_component frontend "${FRONTEND_CMD[@]}"
fi

printf '[stack] target selection is now handled by pi via project skills.\n'
printf '[stack] stack only starts perception and viewer.\n'
printf '[stack] use e-agent to bootstrap the main runner session and enter pi.\n'
printf '[stack] start robot-agent-tracking-loop separately only if you want continuous tracking.\n'
printf '[stack] backend ws: ws://%s:%s\n' "${BACKEND_HOST}" "${BACKEND_PORT}"
if [[ "${START_FRONTEND}" == "1" ]]; then
  printf '[stack] frontend: http://%s:%s\n' "${FRONTEND_HOST}" "${FRONTEND_PORT}"
else
  printf '[stack] frontend is not started by stack.\n'
  printf '[stack] start it manually: bash scripts/run_tracking_frontend.sh --host %s --port %s --ws-url ws://%s:%s\n' "${FRONTEND_HOST}" "${FRONTEND_PORT}" "${BACKEND_HOST}" "${BACKEND_PORT}"
fi

wait
