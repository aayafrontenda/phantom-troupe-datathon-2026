"""Jury API (section 10 of the brief). Paths and the mandatory fields never change."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from .. import metrics
from ..auth import Principal, rate_limit_subject, require_role
from ..storage import save_upload

router = APIRouter(prefix="/api/v1", tags=["jury"])


@router.get("")
def index(request: Request):
    """What the jury sees when opening the API address in a browser: where to send videos and how."""
    st = request.app.state.st
    return {"service": "CashGuard", "version": st.settings.version, "api": "v1", "auth": "X-API-Key header",
            "endpoints": {"analyze": "POST /api/v1/analyze (multipart, field 'file', .mov)",
                          "job": "GET /api/v1/jobs/{job_id}", "rules": "GET /api/v1/rules"},
            "docs": "/docs", "health": "/health"}


@router.post("/analyze")
async def analyze(request: Request, file: UploadFile = File(...), p: Principal = Depends(require_role("jury"))):
    st = request.app.state.st
    if not st.limiter.allow(rate_limit_subject(request)):
        raise HTTPException(status_code=429, detail="Слишком много загрузок, повторите позже")
    t0 = time.time()
    up = await save_upload(file)
    metrics.UPLOAD_BYTES.inc(up.size)
    metrics.UPLOAD_SECONDS.observe(time.time() - t0)
    job = st.jobs.create(up, source="jury", request_started_at=t0, principal=p.name)
    return {"job_id": job["job_id"], "status": "processing" if job["status"] != "done" else "done"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, p: Principal = Depends(require_role("jury"))):
    st = request.app.state.st
    job = st.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return st.jobs.public_view(job)


@router.get("/rules")
def rules(request: Request, p: Principal = Depends(require_role("jury"))):
    from ml import kb
    data = kb.load_kb()
    return {"types": [{"code": c, "type": v["type_name"], "visual": v.get("visual"), "norm_kind": v.get("norm_kind"),
                       "refs": kb.refs_struct(c)} for c, v in data["violations"].items()],
            "sources": data["sources"]}
