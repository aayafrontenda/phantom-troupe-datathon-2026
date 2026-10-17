"""FastAPI-сервис.

API для жюри (раздел 10 ТЗ), ключ в заголовке X-API-Key:
    POST /api/v1/analyze          multipart, поле file (.mov) -> {"job_id": ...}
    GET  /api/v1/jobs/{job_id}    -> {"job_id", "status", "verdict", "violations", ...}

API для веб-интерфейса (без ключа, если UI_REQUIRE_KEY=0):
    POST /ui/api/analyze, GET /ui/api/jobs/{id}, POST /ui/api/jobs/{id}/feedback,
    GET /ui/api/info, WS /ui/api/live

Запуск:  uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import hmac
import json
import logging
import shutil
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .jobs import JobStore, Worker, public_view

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler(config.STORAGE_DIR / "server.log", encoding="utf-8")])
log = logging.getLogger("backend")


def _load_analyzer():
    if config.ANALYZER == "ml":
        from ml.pipeline import analyze
        return analyze
    from ml.mock import analyze_mock
    return analyze_mock


store = JobStore(config.JOBS_DIR)
worker = Worker(store, _load_analyzer())
STATE = {"warmup": "skipped"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _startup()
    yield


app = FastAPI(title="Forte CashGuard", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


def _startup() -> None:
    worker.start()
    log.info("ANALYZER=%s  STORAGE=%s", config.ANALYZER, config.STORAGE_DIR)
    log.info("API-ключ для жюри: %s…  (полностью: storage/api_key.txt или переменная API_KEY)", config.API_KEY[:6])
    if config.ANALYZER == "ml" and config.WARMUP:
        threading.Thread(target=_warmup, daemon=True).start()


def _warmup() -> None:
    """Загрузить детектор и разбудить VLM заранее, чтобы первая задача жюри не ждала."""
    STATE["warmup"] = "running"
    try:
        from ml.detector import get_detector
        from ml.vlm import VLMClient
        get_detector()
        vlm = VLMClient()
        STATE["vlm"] = vlm.ping() if vlm.enabled else "disabled"
        STATE["warmup"] = "done"
    except Exception as e:  # сервис должен работать и без прогрева
        STATE["warmup"] = f"failed: {e}"
        log.exception("warmup failed")


# ---------- ключ ----------

def _check(key: str | None) -> None:
    if not key or not hmac.compare_digest(key, config.API_KEY):
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий X-API-Key")


def require_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    _check(x_api_key)


def ui_access(x_api_key: str | None = Header(default=None, alias="X-API-Key"),
              key: str | None = Query(default=None)) -> None:
    if config.UI_REQUIRE_KEY:
        _check(x_api_key or key)


# ---------- общая логика ----------

async def _accept_upload(file: UploadFile) -> dict:
    name = file.filename or "video.mov"
    ext = Path(name).suffix.lower()
    if ext not in config.ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Ожидается видео .mov (получено: {ext or 'без расширения'})")
    tmp = config.UPLOAD_DIR / f"upload-{time.time_ns()}{ext}"
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    with open(tmp, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                tmp.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Файл больше {config.MAX_UPLOAD_MB} МБ")
            out.write(chunk)
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Пустой файл")
    try:
        from ml.video import probe
        info = probe(tmp)
        if info.frame_count <= 0:
            raise ValueError("нет кадров")
    except Exception:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Не удалось прочитать видео") from None

    job = store.new(name, tmp)
    final = config.UPLOAD_DIR / f"{job['job_id']}{ext}"
    shutil.move(str(tmp), final)
    store.update(job["job_id"], upload_path=str(final), duration_sec=round(info.duration, 2))
    worker.submit(job["job_id"])
    return {"job_id": job["job_id"], "status": "processing"}


def _get(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return job


# ---------- API для жюри ----------

@app.post("/api/v1/analyze", dependencies=[Depends(require_key)])
async def analyze(file: UploadFile = File(...)):
    return await _accept_upload(file)


@app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_key)])
def get_job(job_id: str):
    return public_view(_get(job_id))


# ---------- API для интерфейса ----------

@app.post("/ui/api/analyze", dependencies=[Depends(ui_access)])
async def ui_analyze(file: UploadFile = File(...)):
    return await _accept_upload(file)


@app.get("/ui/api/jobs/{job_id}", dependencies=[Depends(ui_access)])
def ui_get_job(job_id: str):
    job = _get(job_id)
    view = public_view(job)
    if job["status"] == "processing":
        view["queue_position"] = worker.queue_size()
    return view


@app.post("/ui/api/jobs/{job_id}/feedback", dependencies=[Depends(ui_access)])
async def ui_feedback(job_id: str, request: Request):
    """Подтверждение / ложное срабатывание от проверяющего. Видео не сохраняем — только метаданные."""
    job = _get(job_id)
    body = await request.json()
    rec = {"ts": time.time(), "job_id": job_id, "filename": job.get("filename"),
           "violation_index": body.get("violation_index"), "decision": body.get("decision"),
           "comment": (body.get("comment") or "")[:1000]}
    viols = (job.get("result") or {}).get("violations") or []
    i = rec["violation_index"]
    if isinstance(i, int) and 0 <= i < len(viols):
        v = viols[i]
        rec.update(type_code=v.get("type_code"), timecode_sec=v.get("timecode_sec"))
    with open(config.STORAGE_DIR / "feedback.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True}


@app.get("/ui/api/info", dependencies=[Depends(ui_access)])
def ui_info():
    from ml.kb import load_kb
    kb = load_kb()
    return {
        "analyzer": config.ANALYZER,
        "warmup": STATE,
        "types": [{"code": c, "type": v["type_name"], "visual": v["visual"], "norm_kind": v.get("norm_kind")}
                  for c, v in kb["violations"].items()],
        "sources": kb["sources"],
    }


@app.websocket("/ui/api/live")
async def ui_live(ws: WebSocket):
    from .live import live_session
    await live_session(ws)


# ---------- служебное ----------

@app.get("/health")
def health():
    return {"status": "ok", "analyzer": config.ANALYZER, "queue": worker.queue_size(), "warmup": STATE["warmup"]}


@app.exception_handler(HTTPException)
async def _http_exc(_: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# Статика: собранный фронт (frontend/dist), иначе резервный интерфейс (backend/static)
_dist = config.REPO_DIR / "frontend" / "dist"
_static = _dist if (_dist / "index.html").exists() else Path(__file__).resolve().parents[1] / "static"
app.mount("/", StaticFiles(directory=_static, html=True), name="static")
