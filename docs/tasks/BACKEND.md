# Backend + live — инструкция

**Кто:** MacBook Pro M5 Pro.
**Отвечаешь за:** `backend/`, `deploy/`, `tools/` — API строго по ТЗ, надёжность, публичный адрес на ROG,
live-режим, алерты, отчёты.

Контекст задачи — `AGENTS.md`, контракт — `docs/api_contract.md`, устройство сервиса — `docs/backend.md`.

---

## 0. Подготовка (Mac)

```bash
git clone <repo> && cd phantom-troupe-datathon-2026
python3.11 -m venv .venv && source .venv/bin/activate      # или python3.12
pip install -r requirements.txt
cp .env.example .env                                         # ANALYZER=mock
pytest -q                                                    # 33 теста зелёные
./deploy/run_server.sh                                       # http://127.0.0.1:8000, /docs — Swagger
```

Положи видео из датасета в `data/open/videos/` и загрузи через интерфейс — mock вернёт ответ с настоящими кадрами.

## 1. Что сделано

| Что | Где |
| --- | --- |
| `POST /api/v1/analyze`, `GET /api/v1/jobs/{id}`, ключ `X-API-Key` (+Bearer), 401/400/413/429, `/api/v1/rules` | `routers/jury.py` |
| Загрузка потоком с SHA-256; дедуп одинаковых файлов → мгновенный результат | `storage.py`, `jobs.py` |
| Очередь с приоритетами (жюри → UI → replay), воркер в отдельном процессе, сторожевой таймер (дедлайн + зависание), ретрай после падения, респавн | `worker.py` |
| Anytime-результат: к 5-й минуте всегда `done` (частичный результат вместо `failed`) | `jobs.py` (`ON_DEADLINE`, `ON_FAILURE`) |
| Проверка и починка ответа по схеме ТЗ перед выдачей | `jobs.sanitize_result` |
| SQLite: задачи, алерты, камеры, ключи, feedback, аудит; восстановление незаконченных задач после рестарта | `db.py`, `jobs.recover` |
| SSE прогресса `/ui/api/jobs/{id}/events`, список задач, статистика | `routers/ui.py`, `sse.py` |
| Алерты: серьёзность по типу, дедуп, эскалация оператор → супервайзер, ack, Telegram-бот с кнопками, webhook с HMAC, e-mail | `alerts/`, `backend/alerts.yaml` |
| Live: WebSocket браузера; RTSP/файл-камеры с реконнектом; снижение fps при занятой GPU; снимок с рамками; WS/MJPEG трансляция | `live/` |
| Печатный акт проверки + фрагменты 10 с (ffmpeg) | `reports.py`, `templates/report.html` |
| Роли и ключи (`ui`/`jury`/`admin`), admin API, журнал аудита | `auth.py`, `routers/admin.py` |
| `/health`, `/ready`, `/metrics` (Prometheus), `/version`, request-id в логах, ротация `storage/server.log` | `routers/system.py`, `logging_setup.py` |
| Хранение видео: жюри — `JURY_VIDEO_TTL_SEC`, операторы и камеры — `VIDEO_RETENTION_DAYS` | `storage.Retention` |
| Нагрузочные инструменты: параллельные загрузки, шторм live-сессий, симуляция камер | `tools/loadtest.py`, `tools/simulate_cameras.py` |
| Docker + compose (профили `gpu`, `vlm`, `public`, `weights`), сеть без интернета для анализа | `deploy/` |

## 2. Что осталось

### 2.1. Деплой на ROG (вместе с ML)
По `deploy/README.md`: `.env` с `ANALYZER=ml`, явные `API_KEY` и `ADMIN_KEY`, `HF_HUB_OFFLINE=1`, `run_server.ps1`, `cloudflared`.
Проверить `GET /ready` = 200 (воркер прогрет) до того, как отдавать адрес жюри. `PUBLIC_URL` в `.env` — для ссылок в алертах.

### 2.2. Проверка «как жюри» на ROG
```bash
python tools/smoke_test.py --url https://<адрес> --key <ключ> --dir data/open/videos --limit 5
python tools/loadtest.py  --url https://<адрес> --key <ключ> --dir data/open/videos --uploads 10 --unique --json loadtest.json
```
Все `done` < 300 с, `partial 0`. Если появляются `partial` — к ML: уменьшать `MAX_VLM_CALLS` / `VLM_TIMEOUT`, или поднимать
`JOB_HARD_LIMIT_SEC` нельзя (жюри ждёт 300 с от начала загрузки). Сам сервис уже никогда не возвращает «ничего».

### 2.3. Цифры для презентации
1. `tools/loadtest.py --ws 200 --fps 2 --seconds 60` на ROG — серверные ms на кадр и доставленный fps → слайд «control plane держит N кабинетов».
2. Пропускная способность детектора (fps при batch 1/8/16, FP16) — от ML; пересчёт в число GPU на 1000 камер.
3. `tools/simulate_cameras.py --count 20` + страница live — живой дашборд на питче; `/metrics` в Grafana на втором экране.
4. Chaos-демо: `kill -9 <pid воркера>` из `/health` посреди задачи → задача доделывается другим процессом (`meta.attempts: 2`).

### 2.4. Telegram
Создать бота у @BotFather, добавить в групповые чаты операторов/супервайзеров, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_*` в `.env`.
Кнопки «Принял / Ложное» под сообщением работают через long-polling — отдельного сервера не нужно.

### 2.5. Фронт (Алдияр)
Новые данные для интерфейса: SSE прогресса, `queue_position`/`eta_sec`, `partial`/`warning`, `clips`, отчёт `report.html`,
центр алертов (`/ui/api/alerts`, `/ui/api/alerts/stream`, ack), камеры (`/ui/api/cameras/{id}/ws`). Всё описано в `docs/api_contract.md`.

## 3. Готово, когда

- [x] `pytest` зелёный; ответы проходят `ml/schema.py`
- [ ] Публичный HTTPS-адрес работает с мобильного интернета; без ключа — 401; `/ready` = 200
- [ ] `loadtest.py --uploads 10 --unique` на ROG: все `done` < 300 с, `partial 0`
- [x] Сервис сам поднимается после падения; незаконченные задачи доделываются; зависший анализ убивается
- [ ] Live-режим на ROG показывает рамки и алерты; камеры-симуляторы для питча
- [x] Видео удаляются через час, в логах нет API-ключа целиком

## Подводные камни

- Не меняй имена и типы обязательных полей ответа — оценка автоматическая. `jobs.sanitize_result` страхует, но не заменяет ML.
- `WORKERS=1` на одну GPU: каждый воркер загружает модели. `uvicorn --workers N` не использовать (состояние в процессе).
- `WORKER_MODE=process` на Windows использует spawn: функция анализа должна быть импортируемой (`ml.pipeline.analyze` — ок).
- Адрес `trycloudflare.com` меняется при перезапуске `cloudflared` — после сдачи не перезапускать.
- Камеры добавляются только admin-ключом (файл-источник = чтение с диска сервера).
