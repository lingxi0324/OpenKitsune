#!/usr/bin/env bash
# OpenKitsune desktop package with optional modules (Linux/macOS)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SETUP_CENTER_DIR="$PROJECT_ROOT/apps/setup-center"
RESOURCE_DIR="$SETUP_CENTER_DIR/src-tauri/resources"

echo "[1/4] Building web frontend..."
cd "$SETUP_CENTER_DIR"
if [[ ! -d node_modules ]]; then
    npm install
fi
npm run build:web

echo "[2/4] Preparing managed Python runtime..."
cd "$PROJECT_ROOT"
uv run --no-sync python "$SCRIPT_DIR/prepare_bootstrap_resources.py" \
    --commit-resources \
    --auto-detect-target-platform \
    --require-python-seed

echo "[3/4] Pre-bundling optional modules..."
uv run --no-sync python "$SCRIPT_DIR/bundle_modules.py"
rm -rf "$RESOURCE_DIR/modules"
if [[ -d "$SCRIPT_DIR/modules" ]]; then
    cp -r "$SCRIPT_DIR/modules" "$RESOURCE_DIR/modules"
fi

echo "[4/4] Building Tauri app..."
cd "$SETUP_CENTER_DIR"
export TAURI_CONFIG='{"bundle":{"resources":["resources/bootstrap/","resources/modules/"]}}'
npx tauri build

echo "Full desktop package build completed."
