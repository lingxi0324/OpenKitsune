#!/usr/bin/env bash
# OpenKitsune desktop package build script (Linux/macOS)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SETUP_CENTER_DIR="$PROJECT_ROOT/apps/setup-center"

echo "[1/3] Building web frontend..."
cd "$SETUP_CENTER_DIR"
if [[ ! -d node_modules ]]; then
    npm install
fi
npm run build:web

echo "[2/3] Preparing managed Python runtime..."
cd "$PROJECT_ROOT"
uv run --no-sync python "$SCRIPT_DIR/prepare_bootstrap_resources.py" \
    --commit-resources \
    --auto-detect-target-platform \
    --require-python-seed

echo "[3/3] Building Tauri app..."
cd "$SETUP_CENTER_DIR"
npm run tauri build

echo "Desktop package build completed."
