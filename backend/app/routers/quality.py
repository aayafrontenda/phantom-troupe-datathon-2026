"""AI quality for supervisors: precision by type, weekly false positives, operators, thresholds, dataset export."""
from __future__ import annotations

import os
import tempfile
import time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ..auth import Principal, require_user

router = APIRouter(prefix="/ui/api/quality", tags=["quality"])


@router.get("")
def quality(request: Request, days: int = Query(30, ge=0, le=3650), camera_id: str | None = None,
            p: Principal = Depends(require_user("supervisor"))):
    return request.app.state.st.quality.stats(days=days, camera_ids=p.camera_ids, camera_id=camera_id)


@router.get("/thresholds")
def thresholds(request: Request, p: Principal = Depends(require_user("supervisor"))):
    st = request.app.state.st
    return {"base": st.settings.quality_base_confidence, "target": st.settings.quality_target_precision,
            "min_samples": st.settings.quality_min_samples, "types": st.quality.thresholds()}


@router.get("/dataset.zip")
def dataset(request: Request, days: int = Query(0, ge=0, le=3650), p: Principal = Depends(require_user("supervisor"))):
    st = request.app.state.st
    rows = st.quality.dataset_rows(days=days, camera_ids=p.camera_ids)
    tmp = tempfile.NamedTemporaryFile(prefix="phantomguard-dataset-", suffix=".zip", delete=False)
    tmp.close()
    counts = st.quality.dataset_zip(rows, tmp.name)
    st.db.audit("dataset.export", p.name, None, {**counts, "days": days})
    name = f"phantomguard-dataset-{time.strftime('%Y%m%d-%H%M')}.zip"
    return FileResponse(tmp.name, media_type="application/zip", filename=name,
                        headers={"X-Examples": str(counts["examples"]), "X-Frames": str(counts["frames"])},
                        background=BackgroundTask(os.unlink, tmp.name))
