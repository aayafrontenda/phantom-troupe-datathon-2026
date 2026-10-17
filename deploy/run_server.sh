#!/usr/bin/env bash
# Run the service on Mac/Linux with auto-restart.   ./deploy/run_server.sh
# ANALYZER=mock (default here) also turns on hot reload of backend/ and ml/ code; static UI files need only a page refresh.
# Real model:  ANALYZER=ml ./deploy/run_server.sh      Force reload on/off:  RELOAD=1|0 ./deploy/run_server.sh
set -u
cd "$(dirname "$0")/.."
[ -f .venv/bin/activate ] && . .venv/bin/activate
export ANALYZER="${ANALYZER:-mock}"
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
