# Контракт API

## API для жюри (раздел 10 ТЗ) — менять нельзя

Ключ в заголовке `X-API-Key`; без верного ключа — `401`.

### `POST /api/v1/analyze`

multipart/form-data, поле `file` — видео `.mov` (~29 МБ).

```json
{"job_id": "3f2a9c1e0b7d", "status": "processing"}
```

Ошибки: `400` — не видео или не читается, `413` — больше `MAX_UPLOAD_MB`, `401` — ключ.

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
      "description": "Кассир кладёт пачку денег на стол, встаёт и уходит; деньги остаются на столе. Это может указывать на нарушение: … Основание: п. 20, п. 22 — Правила осуществления кассовых операций … (постановление Правления НБРК от 29.11.2019 № 231).",
      "evidence_frames": [{"timestamp_sec": 9.0, "image_base64": "/9j/4AAQ..."}]
    }
  ]
}
```

| Поле | Значения |
| --- | --- |
| `status` | `processing` · `done` · `failed` |
| `verdict` | `violation` · `no_violation` (только при `done`) |
| `violations` | пустой список при `no_violation` |
| `timecode_sec` | секунды от начала видео, 1 знак после запятой |
| `evidence_frames` | 1–3 JPEG в base64, у каждого `timestamp_sec` |

Норма дублируется в конце `description`: автооценка видит только поля схемы.

### Дополнительные поля (жюри их игнорирует, интерфейс использует)

На уровне нарушения:
- `type_code` — `T01`…`T15` (см. `ml/rules_kb.yaml`)
- `confidence` — 0…1
- `rule` — `{"kind": "direct|indirect|internal", "refs": [{"document", "act", "point", "quote", "paraphrase", "url"}], "caveat"}`
- `source` — `vlm` · `detector` · `mock`

На уровне задачи:
- `stage` — `queued` · `started` · `frames` · `detection` · `vlm` · `report` · `done` · `failed`
- `progress` — 0…1
- `timeline` — дорожки состояний: `{"t": [...], "people": [...], "screen_on": [0/1], "phone": [...], "drink": [...], "bag": [...]}` (значение на каждый кадр выборки, 2 кадра/с);
  `detections` — рамки детектора на каждый кадр выборки: `[[группа, score, x1, y1, x2, y2], …]`, координаты в долях кадра (0…1)
- `meta` — `duration_sec`, `processing_sec`, `vlm_calls`, `candidates`, `scenes`, …
- `processing_sec` — от загрузки до результата
- `error` — текст ошибки при `failed`

Полный пример с настоящими кадрами: `examples/sample_response.json`.

### curl

```bash
curl -X POST https://<адрес>/api/v1/analyze -H "X-API-Key: <ключ>" -F "file=@video_017.mov"
curl https://<адрес>/api/v1/jobs/<job_id> -H "X-API-Key: <ключ>"
```

## API для веб-интерфейса

Без ключа (если `UI_REQUIRE_KEY=0`), с тем же форматом ответов.

| Метод | Путь | Что делает |
| --- | --- | --- |
| POST | `/ui/api/analyze` | загрузка, как `/api/v1/analyze` |
| GET | `/ui/api/jobs/{id}` | статус и результат + `queue_position` во время обработки |
| POST | `/ui/api/jobs/{id}/feedback` | `{"violation_index": 0, "decision": "confirm" \| "reject", "comment": "..."}` → `storage/feedback.jsonl` |
| GET | `/ui/api/info` | список типов нарушений и источников (для справки в интерфейсе) |
| WS | `/ui/api/live` | live-режим, протокол ниже |
| GET | `/health` | `{"status": "ok", "analyzer", "queue", "warmup"}` |

### WebSocket `/ui/api/live`

Клиент → сервер: `{"image": "data:image/jpeg;base64,..."}` (или бинарное сообщение с JPEG), 2–4 кадра в секунду, ширина ≤ 640.

Сервер → клиент на каждый кадр:

```json
{
  "detections": [{"group": "phone", "label": "cell phone", "score": 0.81, "box": [x1, y1, x2, y2]}],
  "alerts": [{"code": "T15", "type": "Смартфон в кассовом помещении", "message": "В кадре мобильный телефон",
              "norm": "п. 12 — Правила …", "severity": "warning", "ts": 1760690000.1}],
  "active": ["T15"],
  "ms": 34,
  "size": [640, 360]
}
```

`alerts` — только новые срабатывания; `active` — что сейчас активно. Группы: `person`, `phone`, `drink`, `food`, `bag`, `laptop`, `book`.
