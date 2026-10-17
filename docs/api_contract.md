# Контракт API

Интерактивная документация: `GET /docs` (Swagger), схема — `GET /openapi.json`.
Все ответы с ошибкой — JSON `{"detail": "...", "status": 4xx, "request_id": "..."}`; заголовок `X-Request-ID` есть в каждом ответе.

## API для жюри (раздел 10 ТЗ) — менять нельзя

Ключ в заголовке `X-API-Key` (принимается и `Authorization: Bearer <ключ>`); без верного ключа — `401`.

### `POST /api/v1/analyze`

multipart/form-data, поле `file` — видео `.mov` (~29 МБ). Тело читается потоком, в памяти не держится.

```json
{"job_id": "3f2a9c1e0b7d", "status": "processing"}
```

Ошибки: `400` — не видео, пустой файл или нет поля `file`; `413` — больше `MAX_UPLOAD_MB`; `401` — ключ; `429` — больше `RATE_LIMIT_PER_MIN` загрузок в минуту.

Повторная загрузка того же файла (SHA-256 совпал, та же версия анализатора) сразу получает готовый результат (`status: "done"`, поле `dedup_of`).

### `GET /api/v1/jobs/{job_id}`

```json
{
  "job_id": "3f2a9c1e0b7d",
  "status": "done",
  "verdict": "violation",
  "violations": [
    {
      "type": "Наличные или ценности оставлены на рабочем месте без присмотра",
      "timecode_sec": 9.0,
      "description": "Кассир кладёт пачку денег на стол, встаёт и уходит; деньги остаются на столе. … Основание: п. 20, п. 22 — Правила … № 231.",
      "evidence_frames": [{"timestamp_sec": 9.0, "image_base64": "/9j/4AAQ..."}]
    }
  ]
}
```

| Поле | Значения |
| --- | --- |
| `status` | `processing` · `done` · `failed` (внутренние `queued`/`running` наружу отдаются как `processing`) |
| `verdict` | `violation` · `no_violation` (только при `done`) |
| `violations` | пустой список при `no_violation`; отсортирован по `timecode_sec` |
| `timecode_sec` | секунды от начала видео, 1 знак после запятой |
| `evidence_frames` | 1–3 JPEG в base64, у каждого `timestamp_sec` |

Перед выдачей ответ проверяется по схеме (`ml/schema.py`) и при необходимости чинится: лишние кадры обрезаются до 3, отсутствующий кадр извлекается из видео по таймкоду, вердикт приводится в соответствие списку нарушений. Что было исправлено — в поле `warning`.

**Гарантия по времени.** Сервис всегда отвечает до истечения 5 минут от начала загрузки: пайплайну передаётся дедлайн `JOB_HARD_LIMIT_SEC` (270 с), а сторожевой таймер убивает зависший процесс анализа и возвращает `done` с тем, что успели найти (`partial: true`). `failed` возможен только при `ON_DEADLINE=failed` / `ON_FAILURE=failed`.

### Дополнительные поля (жюри их игнорирует, интерфейс использует)

На уровне нарушения: `type_code` (`T01`…`T15`), `confidence` (0…1), `rule` (`{"kind": "direct|indirect|internal", "refs": [{"document", "act", "point", "quote", "paraphrase", "url"}], "caveat"}`), `source` (`vlm` · `detector` · `mock`).

На уровне задачи:
- `stage` — `queued` · `started` · `frames` · `detection` · `vlm` · `report` · `retry` · `done` · `failed`
- `progress` — 0…1; `queue_position` (0 = следующая) и `eta_sec` — пока задача в очереди/обработке
- `partial` — `true`, если результат частичный (дедлайн, зависание, падение воркера)
- `warning` — что пошло не по плану (частичный результат, исправления схемы); `error` — текст ошибки при `failed`
- `dedup_of` — id задачи, чей результат скопирован
- `timeline`, `meta` (`duration_sec`, `processing_sec`, `vlm_calls`, `candidates`, `scenes`, `analyzer`, `worker`, `attempts`, `partial`, `service_version`)
- `timeline.detections` — рамки детектора на каждый кадр выборки (2 кадра/с): `[[группа, score, x1, y1, x2, y2], …]`, координаты в долях кадра (0…1)
- `processing_sec` — от начала загрузки до результата; `filename`, `duration_sec`, `created_at`, `analyzer`

### `GET /api/v1`

Без ключа: `{"service": "CashGuard", "version", "api": "v1", "auth", "endpoints", "docs", "health"}` — чтобы по адресу API было видно, куда слать видео.
На хостах из `API_HOSTS` (отдельный домен API) интерфейса нет: `/` отдаёт этот же JSON, остальные не-API пути — 404.

### `GET /api/v1/rules`

Реестр типов нарушений и нормативных источников (из `ml/rules_kb.yaml`) — жюри может проверить ссылки.

### curl

```bash
curl -X POST https://<адрес>/api/v1/analyze -H "X-API-Key: <ключ>" -F "file=@video_017.mov"
curl https://<адрес>/api/v1/jobs/<job_id> -H "X-API-Key: <ключ>"
```

## API для веб-интерфейса `/ui/api/*`

Вход по сессии (cookie `cg_session`) под одной из ролей — **operator < supervisor < admin**. Ключ `ADMIN_KEY`
(заголовок `X-API-Key`) работает как admin для скриптов и тестов. `AUTH_REQUIRED=0` открывает UI без входа
(только для разработки). Первые пользователи создаются из `SEED_USERS` в `.env`.

### Вход и пользователи

| Метод | Путь | Что делает |
| --- | --- | --- |
| POST | `/ui/api/auth/login` | `{"login", "password"}` → cookie сессии + `{"user": {name, login, role, camera_ids}}` |
| POST | `/ui/api/auth/logout` | закрыть сессию |
| GET | `/ui/api/auth/me` | текущий пользователь, анализатор, версия, включённые функции |
| GET | `/ui/api/users` | **admin** · список пользователей |
| POST | `/ui/api/users` | **admin** · `{"login", "password", "role", "name", "camera_ids": null \| ["cam1"]}` (`null` = все камеры) |
| PATCH | `/ui/api/users/{id}` | **admin** · `name, role, active, password, camera_ids, all_cameras, unlink_telegram` |
| GET | `/ui/api/auth/telegram` | `{enabled, bot, linked, telegram{username, linked_at}, photos}` |
| POST | `/ui/api/auth/telegram/link` | одноразовая ссылка `https://t.me/<bot>?start=<code>` (15 мин) — привязать свой Telegram |
| DELETE | `/ui/api/auth/telegram` | отвязать свой Telegram |

Операторы видят только назначенные им камеры (`camera_ids`), супервайзеры и админы — все.

### Задачи (загруженные видео)

| Метод | Путь | Что делает |
| --- | --- | --- |
| POST | `/ui/api/analyze` | загрузка, как `/api/v1/analyze` (приоритет ниже, чем у жюри); видео хранится `VIDEO_RETENTION_DAYS` (0 = всегда) |
| GET | `/ui/api/jobs` | последние задачи (`?limit=50&source=ui`) с `created_by`, `reviewed/confirmed/rejected` |
| GET | `/ui/api/jobs/{id}` | статус и результат + `queue_position`, `eta_sec`, `clips`, `findings[]` (находки с решениями), `video_available` |
| DELETE | `/ui/api/jobs/{id}` | отменить (если идёт анализ) или удалить задачу с видео, результатом, находками и алертами |
| GET | `/ui/api/jobs/{id}/events` | **SSE**: `snapshot` → `progress`… → `done` / `failed`; после завершения — `finding_update` |
| GET | `/ui/api/jobs/{id}/video` | загруженное видео (206 Range) |
| GET | `/ui/api/jobs/{id}/report.html?lang=ru\|kk\|en` | печатный отчёт: вердикт, кадры, нормы, формулировка оператора, решение, проверка супервайзера |
| GET | `/ui/api/jobs/{id}/violations/{i}/clip.mp4` | фрагмент 10 с вокруг нарушения |
| GET | `/ui/api/info`, `/ui/api/rules`, `/ui/api/stats`, `/ui/api/i18n/kb` | типы нарушений и нормы, статистика, переводы типов и норм (en/kk) |

### Находки (findings) — единый объект для проверки

Находка создаётся на каждое нарушение из загруженного видео (`source=upload`, `job_id` + `violation_index`)
и на каждую тревогу с камеры (`source=camera`, `camera_id`, `alert_id`, кадры и клип ±8/4 с вокруг момента).
Сценарий: ИИ описал → оператор может уточнить формулировку и решает `confirm` / `reject` → супервайзер
проверяет решение (`agree` / `disagree`). Все шаги в `history`.

| Метод | Путь | Что делает |
| --- | --- | --- |
| GET | `/ui/api/findings?source=&decision=pending\|confirm\|reject\|decided&verified=true\|false&type_code=&camera_id=&decided_by=&edited=&since=&until=&q=&limit=&offset=` | список + `total` + `counts{pending, confirmed, rejected, to_verify, rejected_unverified, verified, disagreed, edited}` |
| GET | `/ui/api/findings/stream` | **SSE**: `finding`, `finding_update`, `finding_deleted` |
| GET | `/ui/api/findings/{id}` | находка целиком: `description_ai`, `description_edit`, `rule`, `frames[]` (base64), `video_url` / `clip_url` / `sequence[]` (кадры камеры), `history[]`, `siblings[]`, `alert` |
| PATCH | `/ui/api/findings/{id}/description` | **operator** · `{"text": "..."}` — формулировка оператора (пустая или равная тексту ИИ = сброс) |
| POST | `/ui/api/findings/{id}/decision` | **operator** · `{"decision": "confirm" \| "reject" \| null, "comment": ""}`; `null` отменяет решение; смена решения снимает проверку |
| POST | `/ui/api/findings/{id}/verify` | **supervisor** · `{"result": "agree" \| "disagree" \| null, "comment": ""}` |
| GET | `/ui/api/findings/{id}/frames/{n}.jpg`, `/clip.mp4` | кадры и фрагмент находки с камеры |
| GET | `/ui/api/findings.csv` | **supervisor** · выгрузка всех находок с решениями (для дообучения и отчётности) |
| DELETE | `/ui/api/findings/{id}` | **admin** |

Решение оператора синхронно закрывает алерт (`resolved` / `false_positive`), отмена — открывает заново.
В списках и карточке есть `below_threshold: true`, если уверенность ИИ ниже адаптивного порога этого типа (см. «Качество ИИ»).

### Качество ИИ (supervisor)

Из решённых находок считается итоговая метка: решение оператора, при `disagree` супервайзера — наоборот.
По меткам: точность по типам, ложные срабатывания по неделям, статистика операторов и **адаптивные пороги**:
если тип подтверждают реже `QUALITY_TARGET_PRECISION` (0,75) при ≥ `QUALITY_MIN_SAMPLES` (10) решениях, порог уверенности
для него поднимается до минимального значения, где подтверждённые примеры достигают цели (шаг 0,05, не выше 0,90).
Порог ничего не скрывает: алерт ниже порога получает серьёзность `low`, находка — флаг `below_threshold`. API жюри не затрагивается.

| Метод | Путь | Что делает |
| --- | --- | --- |
| GET | `/ui/api/quality?days=30\|7\|0&camera_id=` | `summary{decided, verified, accuracy, coverage, flagged, accuracy_delta_pp, basis}`, `by_type[]` (с `threshold{base, applied, status: few\|ok\|raised\|retrain}`), `weekly[]` (8 недель), `operators[]` (`reject_rate`, `disagree_rate`, `flagged`, `flag_reason`), `thresholds`, `dataset` |
| GET | `/ui/api/quality/thresholds` | пороги по типам |
| GET | `/ui/api/quality/dataset.zip?days=0` | датасет для дообучения: `labels.jsonl` + `labels.csv` (тип, уверенность, решение оператора и его формулировка, результат супервайзера, итоговая метка) + `frames/<id>/*.jpg`. Видео жюри исключены |

### Алерты

Алерт — объект с жизненным циклом `open → acknowledged | resolved | false_positive`. Создаётся на каждое нарушение из задачи и на каждое срабатывание live-правил; политика (серьёзность по типу, кому слать, через сколько эскалировать) — `backend/alerts.yaml`.

| Метод | Путь | Что делает |
| --- | --- | --- |
| GET | `/ui/api/alerts?state=open&camera_id=&limit=100` | список с доставками по каналам |
| GET | `/ui/api/alerts/summary` | открытые, по серьёзности, по состоянию, среднее время реакции (MTTA) |
| GET | `/ui/api/alerts/stream` | **SSE**: `alert`, `alert_update`, `alert_escalated` (сначала 20 последних) |
| POST | `/ui/api/alerts/{id}/ack` | `{"decision": "acknowledged" \| "resolved" \| "false_positive", "comment": ""}` |

Объект алерта: `id, severity (critical|high|medium|low|info), state, type_code, type_name, message, camera_id, job_id, finding_id, count, escalation_level, escalate_at, acked_by, acked_at, payload{t_sec, filename, norm, link,…}, deliveries[{channel, target, status}]`.

Каналы: `web` (SSE, всегда), `telegram` (бот, см. ниже), `webhook` (JSON с `X-Signature: sha256=HMAC`), `email` (SMTP). Включаются переменными окружения.
Алерты по видео жюри уходят только в `web` — во внешние каналы тестовые видео не передаются (раздел 10 ТЗ).

**Telegram-бот** (`backend/app/telegram.py`) — только уведомления, решения принимаются на сайте (там клип, таймкод и норма).
Пользователь привязывает свой Telegram в интерфейсе (меню профиля → Telegram). С учётом камер пользователя:

| Роль | Что приходит |
| --- | --- |
| operator | «Найдено возможное нарушение»: тип, камера/видео, таймкод, кадр, кнопка «Открыть в CashGuard» (по загрузкам — только тому, кто загрузил) |
| supervisor | «Оператор отклонил находку ИИ»: описание ИИ, формулировка и комментарий оператора, ссылка |
| admin | ничего |

Команды: `/pending` (что ждёт решения на сайте), `/status`, `/lang ru|kk|en`, `/stop`. Кнопка-ссылка появляется, только если
`PUBLIC_URL` — https. Опрашивать бота может один сервер на токен (`TELEGRAM_POLL=1` в Docker, `0` в `.env` для локальных).
`TELEGRAM_PHOTOS=0` — без кадров, только текст.

### Live

| Метод | Путь | Что делает |
| --- | --- | --- |
| WS | `/ui/api/live` | браузер шлёт кадры, сервер отвечает детекциями (протокол ниже) |
| GET | `/ui/api/cameras` | список камер с состоянием (`online/offline/stopped`, fps, ms) |
| POST | `/ui/api/cameras` | **admin** · `{"id": "cam1", "name": "Касса 1", "url": "rtsp://…" \| "0" \| "/path/video.mov", "fps": 4, "loop": true}` |
| PATCH / DELETE | `/ui/api/cameras/{id}` | **admin** · изменить / удалить |
| GET | `/ui/api/cameras/{id}/snapshot.jpg` | последний кадр с рамками (`?annotated=false` — без) |
| WS | `/ui/api/cameras/{id}/ws` | сервер пушит `{"type":"frame","frame":<base64 JPEG>,"detections":[…],"alerts":[…],"active":[…],"ms":…}` |
| GET | `/ui/api/cameras/{id}/mjpeg` | тот же поток как `<img src>` (multipart/x-mixed-replace) |

Источник камеры — RTSP/HTTP-URL, индекс веб-камеры (`"0"`) или путь к файлу (зацикливается, играет в реальном времени — для демо и стресс-теста: `tools/simulate_cameras.py`).
Пока обрабатываются задачи жюри, live-кадры анализируются с частотой `LIVE_FPS_BUSY`.

#### WebSocket `/ui/api/live`

Клиент → сервер: `{"image": "data:image/jpeg;base64,..."}` (или бинарное сообщение с JPEG), 2–4 кадра в секунду, ширина ≤ 640; `{"ping": 1}` → `{"pong": ts}`.

Сервер → клиент на каждый кадр:

```json
{
  "detections": [{"group": "phone", "label": "cell phone", "score": 0.81, "box": [x1, y1, x2, y2]}],
  "alerts": [{"code": "T15", "type": "Смартфон в кассовом помещении", "message": "В кадре мобильный телефон",
              "norm": "п. 12 — Правила …", "severity": "warning", "ts": 1760690000.1}],
  "active": ["T15"],
  "ms": 34,
  "busy": false,
  "size": [640, 360]
}
```

`alerts` — только новые срабатывания; `active` — что сейчас активно. Группы: `person`, `phone`, `drink`, `food`, `bag`, `laptop`, `book` (с `ANALYZER=mock` — `motion`). При занятой GPU может прийти `{"skipped": true, "busy": true}`.

## Admin API `/admin/api/*` (ключ с ролью admin: `ADMIN_KEY`, по умолчанию = `API_KEY`)

| Метод | Путь | Что делает |
| --- | --- | --- |
| GET / POST / DELETE | `/admin/api/keys` | ключи с ролями `ui` / `jury` / `admin` (хранятся хэшами, ключ показывается один раз) |
| GET | `/admin/api/config` | настройки без секретов + политика алертов |
| GET | `/admin/api/audit` | журнал действий (создание задач, алерты, ключи, камеры) |
| GET | `/admin/api/workers` | состояние воркеров (pid, прогрев, выполнено задач) |
| POST | `/admin/api/jobs/{id}/requeue` | повторный прогон задачи (например, после обновления модели) с низким приоритетом |
| POST | `/admin/api/retention/run` | запустить удаление по TTL сейчас |

## Служебные

| Путь | Что |
| --- | --- |
| `GET /health` | всегда 200: анализатор, очередь, воркеры, прогрев, камеры, версия, uptime |
| `GET /ready` | 200 только когда воркер прогрет и БД отвечает (иначе 503) — для проб и туннеля |
| `GET /metrics` | Prometheus: задачи по статусам, время анализа и «от загрузки до результата», глубина очереди, алерты, live-кадры, HTTP |
| `GET /version` | версия (git sha), анализатор, режим воркера |
