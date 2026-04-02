#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIEWER_DIR="${ROOT_DIR}/apps/tracking-viewer"
HOST="127.0.0.1"
PORT="5173"
WS_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --ws-url)
      WS_URL="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

cd "${VIEWER_DIR}"
if [[ -n "${WS_URL}" ]]; then
  export VITE_TRACKING_VIEWER_WS_URL="${WS_URL}"
fi
exec npm run dev -- --host "${HOST}" --port "${PORT}"
