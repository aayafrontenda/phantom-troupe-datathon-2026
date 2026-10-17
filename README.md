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
ollama pull qwen2.5vl:7b
copy .env.example .env           # ANALYZER=ml
powershell -ExecutionPolicy Bypass -File deploy\run_server.ps1
```

Датасет кейса кладите в `data/open/` (папка в `.gitignore` — видео кейса публиковать нельзя).

## API (раздел 10 ТЗ)

```bash
curl -X POST http://127.0.0.1:8000/api/v1/analyze -H "X-API-Key: <ключ>" -F "file=@video.mov"
curl http://127.0.0.1:8000/api/v1/jobs/<job_id> -H "X-API-Key: <ключ>"
```

Ключ — `API_KEY` в `.env` или сгенерированный в `storage/api_key.txt`. Подробно — `docs/api_contract.md`.

## Полезные команды

| Команда | Что делает |
| --- | --- |
| `python -m ml.cli <video.mov> --no-images` | анализ одного видео в консоли |
| `python -m ml.eval.evaluate --videos data/open/videos` | метрики на 42 метках обучающего датасета |
| `python tools/smoke_test.py --url <адрес> --key <ключ> --dir data/open/videos --limit 5` | проверка «как жюри» |
| `python tools/gen_norms_md.py` | пересобрать `docs/norms.md` из `ml/rules_kb.yaml` |

## Архитектура

```
видео .mov ─► кадры 2 fps ─► RT-DETR (люди, телефон, напитки, сумки, ноутбук)
                               │
                               ▼
                    сигналы состояния + кандидаты событий
                               │  (≤ 12 окон по 6 с)
                               ▼
                 Qwen2.5-VL-7B (локально, Ollama) — чек-лист T01–T15
                               │
                               ▼
        слияние + порог ─► rules_kb.yaml (тип, описание, норма) ─► JSON по ТЗ
```

Модели и лицензии: RT-DETR r18 (Apache-2.0), Qwen2.5-VL-7B-Instruct (Apache-2.0), Ollama (MIT), OpenCV (Apache-2.0), FastAPI (MIT).
# phantom-troupe-datathon-2026
