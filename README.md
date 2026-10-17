# CashGuard — выявление нарушений кассовой дисциплины по видео

Datathon 26, кейс ForteBank. Локальный AI-сервис: загружаете видео с камеры над кассой — получаете вердикт,
нарушения с таймкодом, кадрами-доказательствами, описанием и ссылкой на норму РК.
Все модели работают внутри сервиса, облачные AI-API не используются.

**Начните с `AGENTS.md`** — там задача, ограничения и устройство кода. Задачи по ролям:
[ML](docs/tasks/ML.md) · [Backend + live](docs/tasks/BACKEND.md) · [Frontend + сдача](docs/tasks/FRONTEND.md).

## Быстрый старт

**Mac / без GPU (mock-анализатор, тот же формат ответа):**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
pytest -q
./deploy/run_server.sh          # http://127.0.0.1:8000
```

**ROG / Windows с моделью:**
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r ml\requirements-ml.txt
ollama pull qwen3.5:4b
copy .env.example .env           # ANALYZER=ml
powershell -ExecutionPolicy Bypass -File deploy\run_server.ps1
```

Датасет кейса кладите в `data/open/` (папка в `.gitignore` — видео кейса публиковать нельзя).

Интерфейс — http://127.0.0.1:8000 (Review / Live wall / Rules), Swagger — `/docs`.

## API (раздел 10 ТЗ)

```bash
curl -X POST http://127.0.0.1:8000/api/v1/analyze -H "X-API-Key: <ключ>" -F "file=@video.mov"
curl http://127.0.0.1:8000/api/v1/jobs/<job_id> -H "X-API-Key: <ключ>"
```

Ключ — `API_KEY` в `.env` или сгенерированный в `storage/api_key.txt`. Подробно — `docs/api_contract.md`, Swagger — `/docs`.

Сервис отвечает **всегда до 5 минут**: анализ идёт в отдельном процессе под сторожевым таймером, при зависании или падении
возвращается частичный результат, а не `failed`. Задачи жюри идут в очереди первыми. Повторная загрузка того же файла
отдаёт результат мгновенно. Устройство сервиса — `docs/backend.md`.

## Полезные команды

| Команда | Что делает |
| --- | --- |
| `python -m ml.cli <video.mov> --no-images` | анализ одного видео в консоли |
| `python -m ml.eval.evaluate --videos data/open/videos` | метрики на 42 метках обучающего датасета |
| `python tools/smoke_test.py --url <адрес> --key <ключ> --dir data/open/videos --limit 5` | проверка «как жюри» |
| `python tools/loadtest.py --url <адрес> --key <ключ> --dir data/open/videos --uploads 10 --unique` | нагрузка: параллельные загрузки, p50/p95 |
| `python tools/loadtest.py --url <адрес> --ws 100 --fps 2 --seconds 30 --dir data/open/videos` | нагрузка: 100 live-сессий |
| `python tools/simulate_cameras.py --url <адрес> --key <admin-ключ> --dir data/open/videos --count 10` | 10 камер-симуляторов для live-дашборда |
| `docker compose -f deploy/docker-compose.yml up -d` | то же в контейнерах (профили `gpu`, `vlm`, `public`, `weights`) |
| `python tools/gen_norms_md.py` | пересобрать `docs/norms.md` из `ml/rules_kb.yaml` |

## Архитектура

Сервис: FastAPI → SQLite → пул воркеров-процессов (приоритет жюри, сторожевой таймер, ретраи) → алерты
(web/Telegram/webhook/e-mail, эскалация) → отчёты (акт + фрагменты). Live: RTSP/файл-камеры и браузер по WebSocket.
Подробно — `docs/backend.md`.

Пайплайн анализа:

```
видео .mov ─► кадры 2 fps ─► RT-DETR (люди, ноутбук, предметы)
                               │
               ┌───────────────┴────────────────┐
               ▼                                ▼
   рабочее место = область вокруг       вход в пустую кассу:
   ноутбука, увеличенный фрагмент       участок двери vs эталон
               │ (≤ 26 вызовов)                 │ (без VLM)
               ▼                                ▼
   Qwen3.5-4B (локально, Ollama)            T04 дверь
   отвечает на вопросы о фактах:
   кассир на месте? экран? деньги?
   сейф? пьёт? телефон? личные вещи?
               │
               ▼
   правила по дорожке состояний → T01 T02 T03 T13 T14 T15
               │
               ▼
        слияние ─► rules_kb.yaml (тип, описание, норма) ─► JSON по ТЗ
```

VLM не решает «есть ли нарушение» — она отвечает на простые вопросы о том, что видно, а нарушение выводят
правила. Так на обучающих видео ложные срабатывания упали с 19 из 20 до единиц.

Модели и лицензии: RT-DETR r18 (Apache-2.0), Qwen3.5-4B (Apache-2.0), Ollama (MIT), OpenCV (Apache-2.0), FastAPI (MIT).
