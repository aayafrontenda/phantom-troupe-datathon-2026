from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from .. import metrics

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request):
    st = request.app.state.st
    pool = st.pool.stats()
    warm = {w["name"]: w["warmup"] for w in pool["workers"]}
    return {"status": "ok", "analyzer": st.settings.analyzer, "queue": pool["queued"], "running": pool["running"],
            "workers": [{k: w[k] for k in ("name", "state", "pid", "jobs_done")} for w in pool["workers"]],
            "warmup": next(iter(warm.values()), None) if len(warm) == 1 else warm,
            "cameras_online": sum(1 for c in st.cameras.states.values() if c.status == "online"),
            "version": st.settings.version, "uptime_sec": round(time.time() - st.started_at, 1)}


@router.get("/ready")
def ready(request: Request):
    st = request.app.state.st
    ok_db = True
    try:
        st.db.one("SELECT 1 AS one")
    except Exception:
        ok_db = False
    ok_pool = st.pool.ready() and not st.pool.fatal
    body = {"ready": ok_db and ok_pool, "db": ok_db, "workers": ok_pool, "fatal": st.pool.fatal}
    return JSONResponse(body, status_code=200 if body["ready"] else 503)


@router.get("/metrics")
def prom_metrics():
    data, ctype = metrics.render()
    return Response(data, media_type=ctype)


@router.get("/version")
def version(request: Request):
    st = request.app.state.st
    return {"version": st.settings.version, "analyzer": st.settings.analyzer, "worker_mode": st.settings.worker_mode}
