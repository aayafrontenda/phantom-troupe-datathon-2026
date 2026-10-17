#!/usr/bin/env bash
# Запуск сервиса на Mac/Linux с автоперезапуском.  ./deploy/run_server.sh
# По умолчанию ANALYZER=mock (Mac без NVIDIA). Для модели: ANALYZER=ml ./deploy/run_server.sh
set -u
cd "$(dirname "$0")/.."
[ -f .venv/bin/activate ] && . .venv/bin/activate
export ANALYZER="${ANALYZER:-mock}"
mkdir -p storage
while true; do
  echo "== $(date +%H:%M:%S) запуск (ANALYZER=$ANALYZER) на http://127.0.0.1:8000"
  python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000   # лог: storage/server.log
  echo "Сервис остановился, перезапуск через 3 с (Ctrl+C, чтобы выйти)"
  sleep 3
done
