#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${TRACKING_SERVER_RUNTIME_DIR:-$ROOT_DIR/runtime/server}"
LOG_DIR="${TRACKING_SERVER_LOG_DIR:-$RUNTIME_DIR/logs}"
COMBINED_LOG="$LOG_DIR/combined.log"

mkdir -p "$LOG_DIR"
touch "$COMBINED_LOG"

exec tail -F "$COMBINED_LOG"
