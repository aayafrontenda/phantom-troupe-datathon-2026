"""Web UI API (same payloads as the jury API plus progress streams, reports, alerts, cameras)."""
from __future__ import annotations

import csv
import io
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .. import metrics
from ..auth import Principal, rate_limit_subject, require_role, ui_access
from ..live import browser_session, camera_stream
from ..i18n import pick_lang
from ..reports import clip_path, render_report
from ..sse import sse_response
from ..storage import save_upload

router = APIRouter(prefix="/ui/api", tags=["ui"])


def _st(request: Request):
    return request.app.state.st


def _job_or_404(st, job_id: str) -> dict:
    job = st.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return job


def _clip_owner(job: dict) -> str:
    """Deduplicated jobs reuse the clips of the job they were copied from."""
    return job.get("dedup_of") or job["job_id"]


# ----------------------------------------------------------------------------- jobs

@router.post("/analyze")
async def ui_analyze(request: Request, file: UploadFile = File(...), p: Principal = Depends(ui_access)):
    st = _st(request)
    if not st.limiter.allow(rate_limit_subject(request)):
        raise HTTPException(status_code=429, detail="Слишком много загрузок, повторите позже")
    t0 = time.time()
    up = await save_upload(file)
    metrics.UPLOAD_BYTES.inc(up.size)
    metrics.UPLOAD_SECONDS.observe(time.time() - t0)
    source = "jury" if p.allows("jury") and p.name == "jury" else "ui"
    job = st.jobs.create(up, source=source, request_started_at=t0, principal=p.name)
    return {"job_id": job["job_id"], "status": "processing" if job["status"] != "done" else "done"}


@router.get("/jobs")
def ui_jobs(request: Request, limit: int = Query(50, ge=1, le=500), p: Principal = Depends(ui_access)):
    return {"jobs": _st(request).jobs.list(limit)}


@router.get("/jobs/{job_id}")
def ui_job(job_id: str, request: Request, p: Principal = Depends(ui_access)):
    st = _st(request)
    job = _job_or_404(st, job_id)
    view = st.jobs.public_view(job)
    owner = _clip_owner(job)
    view["clips"] = [i for i in range(len(view.get("violations") or [])) if clip_path(owner, i).exists()]
    view["decisions"] = {str(k): v for k, v in st.jobs.decisions(job_id).items()}
    view["video_available"] = bool(job.get("upload_path") and Path(job["upload_path"]).exists())
    return view


@router.delete("/jobs/{job_id}")
def ui_job_delete(job_id: str, request: Request, p: Principal = Depends(ui_access)):
    """Cancel a queued/running check or remove a finished one (video, result, clips, alerts)."""
    if not _st(request).jobs.delete(job_id, actor=p.name):
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return {"ok": True}


@router.get("/jobs/{job_id}/events")
async def ui_job_events(job_id: str, request: Request, p: Principal = Depends(ui_access)):
    """SSE: progress / done / failed for one job. Closes after the terminal event."""
    st = _st(request)
    job = _job_or_404(st, job_id)
    initial = [{"topic": f"job:{job_id}", "type": "snapshot", "job_id": job_id, "status": job["status"],
                "stage": job.get("stage"), "progress": job.get("progress")}]
    if job["status"] in ("done", "failed"):
        initial.append({"topic": f"job:{job_id}", "type": job["status"], "job_id": job_id})
    return sse_response(st.bus, f"job:{job_id}", initial, until=lambda e: e.get("type") in ("done", "failed"))


class Feedback(BaseModel):
    violation_index: int | None = None
    decision: str = Field(pattern="^(confirm|reject|wrong_type|clear)$")
    comment: str = ""
    correct_type: str | None = None


@router.post("/jobs/{job_id}/feedback")
def ui_feedback(job_id: str, body: Feedback, request: Request, p: Principal = Depends(ui_access)):
    st = _st(request)
    job = _job_or_404(st, job_id)
    result = st.jobs.load_result(job_id) or {}
    viols = result.get("violations") or []
    rec = {"job_id": job_id, "violation_index": body.violation_index, "decision": body.decision,
           "comment": (body.comment or "")[:1000] + (f" [correct_type={body.correct_type}]" if body.correct_type else ""),
           "filename": job.get("filename"), "created_at": time.time()}
    if body.violation_index is not None and 0 <= body.violation_index < len(viols):
        v = viols[body.violation_index]
        rec.update(type_code=v.get("type_code"), timecode_sec=v.get("timecode_sec"))
    fid = st.db.insert("feedback", rec)
    st.db.audit("feedback", p.name, job_id, {"id": fid, "decision": body.decision})
    if rec.get("type_code") is not None or body.violation_index is not None:
        try:
            st.alerts.sync_review(job_id, rec.get("type_code"), rec.get("timecode_sec"), body.decision, p.name)
        except Exception:
            import logging
            logging.getLogger("backend.ui").exception("alert sync failed for job %s", job_id)
    return {"ok": True, "id": fid}


@router.get("/jobs/{job_id}/feedback")
def ui_job_feedback(job_id: str, request: Request, p: Principal = Depends(ui_access)):
    st = _st(request)
    _job_or_404(st, job_id)
    rows = st.db.all("SELECT id, violation_index, decision, comment, created_at FROM feedback WHERE job_id=? ORDER BY id",
                     (job_id,))
    return {"feedback": rows}


@router.get("/jobs/{job_id}/video")
def ui_job_video(job_id: str, request: Request, p: Principal = Depends(ui_access)):
    """The uploaded recording, while it still exists (deleted VIDEO_TTL_SEC after the job finishes)."""
    st = _st(request)
    job = _job_or_404(st, job_id)
    path = job.get("upload_path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Видео уже удалено по TTL")
    ext = Path(path).suffix.lower()
    media = "video/quicktime" if ext == ".mov" else "video/mp4"
    return FileResponse(path, media_type=media, filename=job.get("filename") or f"{job_id}{ext}",
                        content_disposition_type="inline")


@router.get("/feedback.csv")
def ui_feedback_csv(request: Request, p: Principal = Depends(ui_access)):
    rows = _st(request).db.all("SELECT * FROM feedback ORDER BY id")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "created_at", "job_id", "filename", "violation_index", "type_code", "timecode_sec", "decision", "comment"])
    for r in rows:
        w.writerow([r["id"], r["created_at"], r["job_id"], r["filename"], r["violation_index"], r["type_code"],
                    r["timecode_sec"], r["decision"], r["comment"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=feedback.csv"})


# ----------------------------------------------------------------------------- reports & clips

@router.get("/jobs/{job_id}/report.html", response_class=HTMLResponse)
def ui_report(job_id: str, request: Request, lang: str | None = None, p: Principal = Depends(ui_access)):
    st = _st(request)
    job = _job_or_404(st, job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Задача ещё не завершена")
    result = st.jobs.load_result(job_id) or {"verdict": "no_violation", "violations": []}
    decisions = st.jobs.decisions(job_id)
    owner = _clip_owner(job)
    clips = {i: f"/ui/api/jobs/{job_id}/violations/{i}/clip.mp4"
             for i in range(len(result.get("violations") or [])) if clip_path(owner, i).exists()}
    lang = pick_lang(lang, request.headers.get("accept-language"))
    return HTMLResponse(render_report(job, result, clips, decisions, lang))


@router.get("/jobs/{job_id}/violations/{index}/clip.mp4")
def ui_clip(job_id: str, index: int, request: Request, p: Principal = Depends(ui_access)):
    job = _job_or_404(_st(request), job_id)
    path = clip_path(_clip_owner(job), index)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Фрагмент не найден (ffmpeg недоступен или видео уже удалено)")
    return FileResponse(str(path), media_type="video/mp4", filename=f"{job_id}_v{index}.mp4")


# ----------------------------------------------------------------------------- info / rules / stats

@router.get("/info")
def ui_info(request: Request, p: Principal = Depends(ui_access)):
    st = _st(request)
    from ml.kb import load_kb
    kb = load_kb()
    pool = st.pool.stats()
    return {
        "analyzer": st.settings.analyzer,
        "version": st.settings.version,
        "warmup": {w["name"]: w["warmup"] for w in pool["workers"]},
        "workers": pool,
        "types": [{"code": c, "type": v["type_name"], "visual": v["visual"], "norm_kind": v.get("norm_kind")}
                  for c, v in kb["violations"].items()],
        "sources": kb["sources"],
        "features": {"clips": st.settings.make_clips, "telegram": bool(st.settings.telegram_bot_token),
                     "webhook": bool(st.settings.alert_webhook_url), "email": bool(st.settings.smtp_host)},
    }


@router.get("/rules")
def ui_rules(request: Request, p: Principal = Depends(ui_access)):
    from ml import kb
    data = kb.load_kb()
    return {"types": [{"code": c, "type": v["type_name"], "visual": v.get("visual"), "why": v.get("why"),
                       "norm_kind": v.get("norm_kind"), "caveat": v.get("caveat"), "refs": kb.refs_struct(c)}
                      for c, v in data["violations"].items()],
            "sources": data["sources"]}


@router.get("/stats")
def ui_stats(request: Request, p: Principal = Depends(ui_access)):
    st = _st(request)
    return {"jobs": st.jobs.stats(), "alerts": st.alerts.summary(), "pool": st.pool.stats(),
            "cameras": [{"id": c["id"], "name": c["name"], **c["state"]} for c in st.cameras.list()],
            "uptime_sec": round(time.time() - st.started_at, 1)}


# ----------------------------------------------------------------------------- alerts

class Ack(BaseModel):
    decision: str = Field(default="acknowledged", pattern="^(acknowledged|resolved|false_positive)$")
    comment: str | None = None


@router.get("/alerts")
def ui_alerts(request: Request, state: str | None = None, camera_id: str | None = None,
              limit: int = Query(100, ge=1, le=1000), p: Principal = Depends(ui_access)):
    return {"alerts": _st(request).alerts.list(state=state, limit=limit, camera_id=camera_id)}


@router.get("/alerts/summary")
def ui_alerts_summary(request: Request, p: Principal = Depends(ui_access)):
    return _st(request).alerts.summary()


@router.get("/alerts/stream")
async def ui_alerts_stream(request: Request, max: int = Query(0, ge=0), p: Principal = Depends(ui_access)):
    """SSE feed of alert events (new / updated / escalated); `max` closes the stream after N events (debug)."""
    st = _st(request)
    count = {"n": 0}

    def until(_e: dict) -> bool:
        count["n"] += 1
        return bool(max) and count["n"] >= max

    return sse_response(st.bus, "alerts", st.bus.recent("alerts", 20), until=until if max else None)


@router.post("/alerts/{alert_id}/ack")
def ui_alert_ack(alert_id: int, body: Ack, request: Request, p: Principal = Depends(ui_access)):
    a = _st(request).alerts.ack(alert_id, by=p.name, decision=body.decision, comment=body.comment)
    if a is None:
        raise HTTPException(status_code=404, detail="Алерт не найден")
    return a


# ----------------------------------------------------------------------------- live

@router.websocket("/live")
async def ui_live(ws: WebSocket):
    st = ws.app.state.st
    await browser_session(ws, on_alert=st._on_live_alert, busy=st.pool.busy)


class CameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=1000)
    fps: float | None = Field(default=None, gt=0, le=30)
    enabled: bool = True
    loop: bool = True
    meta: dict | None = None
    id: str | None = Field(default=None, pattern="^[A-Za-z0-9_-]{1,32}$")


class CameraPatch(BaseModel):
    name: str | None = None
    url: str | None = None
    fps: float | None = Field(default=None, gt=0, le=30)
    enabled: bool | None = None
    loop: bool | None = None
    meta: dict | None = None


@router.get("/cameras")
def ui_cameras(request: Request, p: Principal = Depends(ui_access)):
    return {"cameras": _st(request).cameras.list()}


@router.post("/cameras", status_code=201)
def ui_camera_add(body: CameraIn, request: Request, p: Principal = Depends(require_role("admin"))):
    st = _st(request)
    if body.id and st.cameras.get(body.id):
        raise HTTPException(status_code=409, detail="Камера с таким id уже есть")
    return st.cameras.add(body.name, body.url, body.fps, body.enabled, body.loop, body.meta, body.id)


@router.get("/cameras/{cam_id}")
def ui_camera(cam_id: str, request: Request, p: Principal = Depends(ui_access)):
    cam = _st(request).cameras.get(cam_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="Камера не найдена")
    return cam


@router.patch("/cameras/{cam_id}")
def ui_camera_patch(cam_id: str, body: CameraPatch, request: Request, p: Principal = Depends(require_role("admin"))):
    st = _st(request)
    if st.cameras.get(cam_id) is None:
        raise HTTPException(status_code=404, detail="Камера не найдена")
    return st.cameras.update(cam_id, **body.model_dump(exclude_none=True))


@router.delete("/cameras/{cam_id}")
def ui_camera_delete(cam_id: str, request: Request, p: Principal = Depends(require_role("admin"))):
    if not _st(request).cameras.remove(cam_id):
        raise HTTPException(status_code=404, detail="Камера не найдена")
    return {"ok": True}


@router.get("/cameras/{cam_id}/snapshot.jpg")
def ui_camera_snapshot(cam_id: str, request: Request, annotated: bool = True, p: Principal = Depends(ui_access)):
    data = _st(request).cameras.snapshot(cam_id, annotated)
    if data is None:
        raise HTTPException(status_code=404, detail="Кадра ещё нет")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.websocket("/cameras/{cam_id}/ws")
async def ui_camera_ws(ws: WebSocket, cam_id: str):
    st = ws.app.state.st
    if st.cameras.get(cam_id) is None:
        await ws.close(code=4404)
        return
    await camera_stream(ws, st.bus, cam_id, lambda: st.cameras.snapshot(cam_id, annotated=False))


@router.get("/cameras/{cam_id}/mjpeg")
async def ui_camera_mjpeg(cam_id: str, request: Request, p: Principal = Depends(ui_access)):
    """Plain <img src> stream for dashboards that cannot use WebSocket."""
    st = _st(request)
    if st.cameras.get(cam_id) is None:
        raise HTTPException(status_code=404, detail="Камера не найдена")

    async def gen():
        import asyncio
        import base64
        sub, q = st.bus.subscribe_async(f"camera:{cam_id}")
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=10)
                except asyncio.TimeoutError:
                    continue
                while not q.empty():
                    msg = q.get_nowait()
                jpg = base64.b64decode(msg["frame"])
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
        finally:
            st.bus.unsubscribe(sub)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")
