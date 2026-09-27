#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="$PWD/.uv-cache"
uv sync
(cd frontend && npm install)
uv run uvicorn reflex.app:app --app-dir backend --host 127.0.0.1 --port 8000 &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true' EXIT INT TERM
cd frontend
npm run dev -- --host 127.0.0.1
