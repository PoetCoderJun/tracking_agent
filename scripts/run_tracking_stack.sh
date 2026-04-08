#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_ROOT="./.runtime/agent-runtime"
OUTPUT_DIR="./.runtime/tracking-perception"
ARTIFACTS_ROOT="./.runtime/pi-agent"
ENV_FILE=".ENV"
SOURCE="camera"
DEVICE_ID="robot_01"
DEVICE=""
TRACKER=""
SESSION_ID=""
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="5173"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8765"
CONTINUE_TEXT="继续跟踪"
REALTIME_PLAYBACK="0"
START_FRONTEND="0"

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
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --artifacts-root)
      ARTIFACTS_ROOT="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --device-id)
      DEVICE_ID="$2"
      shift 2
      ;;
    --device)
      DEVICE="$2"
      shift 2
      ;;
    --tracker)
      TRACKER="$2"
      shift 2
      ;;
    --session-id)
      SESSION_ID="$2"
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
    --continue-text)
      CONTINUE_TEXT="$2"
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

if [[ -z "${SESSION_ID}" ]]; then
  SESSION_ID="session_$(date -u +"%Y%m%dT%H%M%S%NZ")"
fi

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
  for pid in "${PIDS[@]:-}"; do
    kill_tree "${pid}"
  done
}

prefix_stream() {
  local default_name="$1"
  local prefix
  local line
  while IFS= read -r line || [[ -n "${line}" ]]; do
    prefix="${default_name}"
    if [[ "${default_name}" == "agent" ]]; then
      case "${line}" in
        *'"status": "tracking_bound"'*|*'"status":"tracking_bound"'*|*'"status": "idle"'*|*'"status":"idle"'*)
          prefix="loop"
          ;;
      esac
    fi
    printf '[%s] %s\n' "${prefix}" "${line}"
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
  kill "${pid}" >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

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

PERCEPTION_CMD=(uv run python -m scripts.run_tracking_perception
  --source "${SOURCE}"
  --output-dir "${OUTPUT_DIR}"
  --session-id "${SESSION_ID}"
  --device-id "${DEVICE_ID}"
  --state-root "${STATE_ROOT}"
  --interval-seconds "1.0"
)
if [[ -n "${DEVICE}" ]]; then
  PERCEPTION_CMD+=(--device "${DEVICE}")
fi
if [[ -n "${TRACKER}" ]]; then
  PERCEPTION_CMD+=(--tracker "${TRACKER}")
fi
if [[ "${REALTIME_PLAYBACK}" == "1" ]]; then
  PERCEPTION_CMD+=(--realtime-playback)
fi

BACKEND_CMD=(uv run python -m viewer.stream
  --state-root "${STATE_ROOT}"
  --host "${BACKEND_HOST}"
  --port "${BACKEND_PORT}"
)

AGENT_CMD=(uv run python -m backend.tracking.service
  --session-id "${SESSION_ID}"
  --device-id "${DEVICE_ID}"
  --state-root "${STATE_ROOT}"
  --env-file "${ENV_FILE}"
  --artifacts-root "${ARTIFACTS_ROOT}"
  --continue-text "${CONTINUE_TEXT}"
)

run_component perception "${PERCEPTION_CMD[@]}"
run_component backend "${BACKEND_CMD[@]}"
run_component agent "${AGENT_CMD[@]}"

if [[ "${START_FRONTEND}" == "1" ]]; then
  FRONTEND_CMD=(bash "${ROOT_DIR}/scripts/run_tracking_frontend.sh"
    --host "${FRONTEND_HOST}"
    --port "${FRONTEND_PORT}"
    --ws-url "ws://${BACKEND_HOST}:${BACKEND_PORT}"
  )
  run_component frontend "${FRONTEND_CMD[@]}"
fi

printf '[stack] session-id: %s\n' "${SESSION_ID}"
printf '[stack] target selection is now handled by pi via project skills.\n'
printf '[stack] use robot-agent session-start to create/attach runtime state if needed.\n'
printf '[stack] backend ws: ws://%s:%s\n' "${BACKEND_HOST}" "${BACKEND_PORT}"
if [[ "${START_FRONTEND}" == "1" ]]; then
  printf '[stack] frontend: http://%s:%s\n' "${FRONTEND_HOST}" "${FRONTEND_PORT}"
else
  printf '[stack] frontend is not started by stack.\n'
  printf '[stack] start it manually: bash scripts/run_tracking_frontend.sh --host %s --port %s --ws-url ws://%s:%s\n' "${FRONTEND_HOST}" "${FRONTEND_PORT}" "${BACKEND_HOST}" "${BACKEND_PORT}"
fi

wait
