# Бэкенд: архитектура сервиса

Сервис — один процесс FastAPI + изолированные процессы анализа + SQLite. Внешних сервисов нет: запускается
одной командой на ноутбуке, переносится в контур банка как есть, растёт до нескольких машин заменой двух модулей.

```
                      ┌────────────────────────────── процесс uvicorn ──────────────────────────────┐
 жюри  ──POST──▶  Gateway/API ──▶ storage.save_upload (поток, SHA-256, ffprobe) ──▶ JobService.create
 UI    ──POST──▶   routers/*          │ dedup по SHA-256 → мгновенный результат         │
                                       ▼                                                 ▼
                              SQLite (jobs, alerts, cameras, keys, audit)     WorkerPool (heap по приоритету)
                                       ▲                                                 │ jury=0 < ui=1 < replay=2
 UI  ◀──SSE/WS──  EventBus ◀── JobService.on_progress / on_finish ◀── reader thread ◀─┤
                                       │                                                 ▼
                              AlertEngine ──▶ web / telegram / webhook / email   ┌───────────────────┐
                                       ▲                                         │ worker process w0 │  ← analyze(path, on_progress, deadline)
                              CameraManager (RTSP / файл) ── live analyzer       │ (модели в памяти) │  ← watchdog: deadline + stall
                                                                                 └───────────────────┘
```

## Модули (`backend/app/`)

| Модуль | Отвечает за |
| --- | --- |
| `config.py` | настройки из env/.env, пути, ключи (`get_settings()`) |
| `db.py` | SQLite (WAL), миграции, транзакции, аудит |
| `auth.py` | роли `ui < jury < admin`, ключи из env и из БД (хэш), rate limit (token bucket) |
| `storage.py` | потоковая загрузка с лимитом и SHA-256, probe видео, TTL-очистка видео/фрагментов/результатов |
| `analyzers.py` | контракт с ML: `analyze(path, on_progress, deadline)`, `on_progress.partial(result)`, `warmup()` |
| `worker.py` | пул воркеров (процесс/поток), очередь с приоритетами, сторожевой таймер, ретраи, респавн |
| `jobs.py` | жизненный цикл задачи, дедуп, `public_view` (поля ТЗ первыми), починка результата по схеме, восстановление после рестарта |
| `events.py` | шина событий поток → asyncio (SSE/WS) |
| `sse.py` | Server-Sent Events поверх шины |
| `alerts/engine.py` | серьёзность по типу, дедуп/cooldown, маршрутизация по ролям, эскалация по таймеру, ack |
| `alerts/channels.py` | web, Telegram (кнопки «Принял/Ложное» через long-polling), webhook (HMAC), e-mail |
| `live/analyzer.py` | live-сессия: детектор + `ml.live.LiveRules` (ml) или движение по MOG2 (mock) |
| `live/cameras.py` | поток на камеру: RTSP/HTTP/веб-камера/файл, реконнект, снижение fps при занятой GPU |
| `live/session.py` | WebSocket браузера и WebSocket-трансляция камеры |
| `reports.py` | печатный акт (Jinja2) и фрагменты 10 с (ffmpeg) |
| `metrics.py` | Prometheus-метрики |
| `routers/` | `jury` (`/api/v1`), `ui` (`/ui/api`), `admin` (`/admin/api`), `system` (`/health /ready /metrics /version`) |
| `state.py` | сборка всех сервисов и хуки: результат → алерты и фрагменты |

## Как задача проходит через сервис

1. `POST /analyze`: ключ → rate limit → тело по 1 МБ на диск с подсчётом SHA-256 → `probe` (есть ли кадры) → запись `jobs`
   (`queued`, `deadline_at = начало_загрузки + JOB_HARD_LIMIT_SEC`) → в очередь с приоритетом источника → `{job_id}`.
   Совпал SHA-256 с готовой задачей той же версии анализатора → результат копируется, статус сразу `done`.
2. Планировщик (`worker.py`) отдаёт задачу первому свободному воркеру: сначала все задачи жюри, потом UI, потом replay.
3. Воркер-процесс вызывает `analyze(...)`. Прогресс идёт в БД и на шину (SSE для интерфейса, `stage/progress` в API).
   Пайплайн может отдать промежуточный результат через `on_progress.partial(...)`.
4. Сторожевой таймер: `deadline + WATCHDOG_GRACE_SEC` или `WORKER_STALL_SEC` без прогресса → процесс убит, запускается новый,
   задача завершается тем, что уже было (`partial: true`). Падение процесса (segfault) → один ретрай, если времени хватает.
5. Финализация: результат проверяется по схеме ТЗ и при необходимости чинится, пишется в `storage/results/<id>.json`,
   статус `done`; на каждое нарушение создаётся алерт; в фоне режутся фрагменты.
6. Видео и фрагменты удаляются через `VIDEO_TTL_SEC`; результат (JSON с кадрами) остаётся.

## Почему так

- **Процесс-изоляция анализа.** Падение torch/CUDA или зависший HTTP к Ollama не роняют API и не теряют задачу —
  раньше всё жило в одном потоке uvicorn и `failed` было единственным исходом.
- **Приоритет жюри.** 5 видео жюри и 20 загрузок из интерфейса одновременно — жюри всё равно первые.
- **Anytime-результат.** Для оценки `failed` и «нет ответа за 5 минут» = 0 баллов, а `done` с частичным результатом —
  шанс на баллы. Поэтому по умолчанию `ON_DEADLINE=partial`, `ON_FAILURE=partial`, и всё это видно в `warning`/метриках.
- **SQLite вместо JSON-файлов.** Атомарные обновления, запросы для статистики и отчётов, аудит; нулевая эксплуатация.
  Для нескольких узлов меняются два класса: `Database` → PostgreSQL, `WorkerPool.submit` → Redis Streams/NATS.
- **Единый контракт с ML.** Бэкенд знает только `analyze()`; модель можно переделывать сколько угодно.

## Масштабирование до 1000 кабинетов

Узкое место — GPU на стадии детекции, не API. План и цифры — в документе «Архитектура сервиса» (раздел «1000 кабинетов»).
Инструменты измерения здесь: `tools/loadtest.py --ws N` (N live-сессий, серверные миллисекунды на кадр, доставленный fps),
`tools/loadtest.py --uploads N --unique` (параллельные загрузки «как жюри»), `tools/simulate_cameras.py` (N камер из файлов),
`/metrics` в Grafana/Prometheus.

Что меняется на пути к 1000 камер (без переписывания): ingest камер выносится в отдельный сервис (тот же `CameraManager`),
воркеров становится N по числу GPU (`WORKERS`, по одному на карту), очередь — Redis Streams, БД — PostgreSQL.

## Проверка

```bash
pytest -q                                           # 33 теста: контракт, приоритеты, дедлайн, краш, рестарт, алерты, live
python tools/smoke_test.py --url http://127.0.0.1:8000 --key $API_KEY --dir data/open/videos --limit 5
python tools/loadtest.py --url http://127.0.0.1:8000 --key $API_KEY --dir data/open/videos --uploads 10 --unique
python tools/loadtest.py --url http://127.0.0.1:8000 --ws 100 --fps 2 --seconds 30 --dir data/open/videos
python tools/simulate_cameras.py --url http://127.0.0.1:8000 --key $ADMIN_KEY --dir data/open/videos --count 10
```
