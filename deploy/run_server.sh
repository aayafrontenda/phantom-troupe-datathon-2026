#!/usr/bin/env bash
# Run the service on Mac/Linux with auto-restart.   ./deploy/run_server.sh
# ANALYZER=mock (default here) also turns on hot reload of backend/ and ml/ code.
# Real model:  ANALYZER=ml ./deploy/run_server.sh      Force reload on/off:  RELOAD=1|0 ./deploy/run_server.sh
# The web UI is built from frontend/ when it is missing or older than its sources (needs Node 20+);
# for live UI development run `npm run dev` in frontend/ instead (proxies the API to :8000).
set -u
cd "$(dirname "$0")/.."
[ -f .venv/bin/activate ] && . .venv/bin/activate
export ANALYZER="${ANALYZER:-mock}"
build_frontend() {
  if ! command -v npm >/dev/null 2>&1; then
    [ -f frontend/dist/index.html ] || echo "!! Node/npm not found and frontend/dist is missing: install Node 20+ and run 'npm ci && npm run build' in frontend/"
    return
  fi
  if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html frontend/package.json -newer frontend/dist/index.html 2>/dev/null | head -1)" ]; then
    echo "== building the web UI (frontend/)"
    (cd frontend && { [ -d node_modules ] || npm ci --silent; } && npm run build --silent) || echo "!! frontend build failed"
  fi
}
build_frontend
ulimit -n 4096 2>/dev/null || true
RELOAD="${RELOAD:-$([ "$ANALYZER" = "mock" ] && echo 1 || echo 0)}"
ARGS=(--host 0.0.0.0 --port "${PORT:-8000}")
[ "$RELOAD" = "1" ] && ARGS+=(--reload --reload-dir backend --reload-dir ml --reload-include "*.yaml")
mkdir -p storage
while true; do
  echo "== $(date +%H:%M:%S) start (ANALYZER=$ANALYZER, reload=$RELOAD) http://127.0.0.1:${PORT:-8000}"
  python -m uvicorn backend.app.main:app "${ARGS[@]}"   # log: storage/server.log
  echo "Service stopped, restarting in 3 s (Ctrl+C to exit)"
  sleep 3
done
