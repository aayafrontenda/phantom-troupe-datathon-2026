from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..auth import Principal, require_role
from ..worker import PRIORITY_REPLAY

router = APIRouter(prefix="/admin/api", tags=["admin"], dependencies=[Depends(require_role("admin"))])


class KeyIn(BaseModel):
    role: str = Field(pattern="^(ui|jury|admin)$")
    name: str = Field(min_length=1, max_length=64)


@router.get("/keys")
def list_keys(request: Request):
    return {"keys": request.app.state.st.keys.list()}


@router.post("/keys", status_code=201)
def create_key(body: KeyIn, request: Request, p: Principal = Depends(require_role("admin"))):
    st = request.app.state.st
    key, kid = st.keys.create(body.role, body.name)
    st.db.audit("key.create", p.name, str(kid), {"role": body.role, "name": body.name})
    return {"id": kid, "role": body.role, "name": body.name, "key": key}


@router.delete("/keys/{kid}")
def revoke_key(kid: int, request: Request, p: Principal = Depends(require_role("admin"))):
    st = request.app.state.st
    if not st.keys.revoke(kid):
        raise HTTPException(status_code=404, detail="Ключ не найден")
    st.db.audit("key.revoke", p.name, str(kid))
    return {"ok": True}


@router.get("/config")
def config(request: Request):
    st = request.app.state.st
    return {"settings": st.settings.safe_dict(), "alerts_policy": st.alerts.policy}


@router.get("/audit")
def audit(request: Request, limit: int = Query(200, ge=1, le=2000)):
    return {"audit": request.app.state.st.db.all("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))}


@router.post("/retention/run")
def retention_run(request: Request):
    return {"removed": request.app.state.st.retention.run_once()}


@router.post("/jobs/{job_id}/requeue")
def requeue(job_id: str, request: Request, p: Principal = Depends(require_role("admin"))):
    st = request.app.state.st
    job = st.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    path = job.get("upload_path")
    if not path or not __import__("pathlib").Path(path).exists():
        raise HTTPException(status_code=409, detail="Видео уже удалено по TTL - повторный прогон невозможен")
    now = time.time()
    st.db.update("jobs", "job_id", job_id, {"status": "queued", "stage": "queued", "progress": 0.0, "partial": 0,
                                            "error": None, "warning": None, "result_path": None, "verdict": None,
                                            "n_violations": None, "dedup_of": None, "request_started_at": now,
                                            "deadline_at": now + st.settings.job_hard_limit_sec, "updated_at": now,
                                            "analyzer": st.jobs.analyzer_version})
    st.pool.submit(job_id, path, PRIORITY_REPLAY, now + st.settings.job_hard_limit_sec)
    st.db.audit("job.requeue", p.name, job_id)
    return {"job_id": job_id, "status": "processing"}


@router.get("/workers")
def workers(request: Request):
    return request.app.state.st.pool.stats()
