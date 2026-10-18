from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..auth import Principal, require_user, ui_access
from ..sse import sse_response

router = APIRouter(prefix="/ui/api", tags=["findings"])


def _st(request: Request):
    return request.app.state.st


def _finding_or_404(st, fid: int, p: Principal, with_frames: bool = False) -> dict:
    f = st.findings.get(fid, with_frames=with_frames)
    if f is None:
        raise HTTPException(status_code=404, detail="Находка не найдена")
    if f["source"] == "camera" and not p.can_see_camera(f["camera_id"]):
        raise HTTPException(status_code=403, detail="Нет доступа к этой камере")
    return f


@router.get("/findings")
def findings_list(request: Request, source: str | None = None, decision: str | None = None,
                  verified: bool | None = None, type_code: str | None = None, camera_id: str | None = None,
                  decided_by: str | None = None, edited: bool | None = None, since: float | None = None,
                  until: float | None = None, q: str | None = None, verify_result: str | None = None,
                  limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), p: Principal = Depends(ui_access)):
    st = _st(request)
    data = st.findings.list(source=source, decision=decision, verified=verified, type_code=type_code,
                            camera_id=camera_id, camera_ids=p.camera_ids, decided_by=decided_by, edited=edited,
                            since=since, until=until, q=q, verify_result=verify_result, limit=limit, offset=offset)
    data["counts"] = st.findings.counts(p.camera_ids)
    data["operators"] = st.findings.operators(p.camera_ids)
    return data


@router.get("/findings/counts")
def findings_counts(request: Request, p: Principal = Depends(ui_access)):
    return _st(request).findings.counts(p.camera_ids)


@router.get("/findings/stream")
async def findings_stream(request: Request, p: Principal = Depends(ui_access)):
    st = _st(request)
    return sse_response(st.bus, "findings", st.bus.recent("findings", 20))


@router.get("/findings.csv")
def findings_csv(request: Request, p: Principal = Depends(require_user("supervisor"))):
    rows = _st(request).findings.export_rows()
    buf = io.StringIO()
    cols = ["id", "source", "created_at", "job_id", "filename", "camera_id", "camera_name", "type_code", "type_name",
            "t_sec", "confidence", "description_ai", "description_edit", "decision", "decided_by", "decided_at",
            "decision_comment", "verified", "verify_result", "verified_by", "verified_at", "verify_comment"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c) for c in cols])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=findings.csv"})


@router.get("/findings/{fid}")
def finding_get(fid: int, request: Request, p: Principal = Depends(ui_access)):
    st = _st(request)
    f = _finding_or_404(st, fid, p, with_frames=True)
    f["history"] = st.findings.history(fid)
    names = st.findings.user_names()
    for h in f["history"]:
        h["actor_name"] = names.get(h.get("actor") or "", h.get("actor"))
    siblings = st.findings.for_job(f["job_id"]) if f.get("job_id") else []
    f["siblings"] = [{"id": x["id"], "violation_index": x["violation_index"], "type_name": x["type_name"],
                      "t_sec": x["t_sec"], "decision": x["decision"]} for x in siblings]
    if f.get("alert_id"):
        f["alert"] = st.alerts.get(f["alert_id"])
    return f


class DescriptionIn(BaseModel):
    text: str = Field(max_length=2000)


@router.patch("/findings/{fid}/description")
def finding_edit(fid: int, body: DescriptionIn, request: Request, p: Principal = Depends(require_user("operator"))):
    st = _st(request)
    _finding_or_404(st, fid, p)
    return st.findings.edit(fid, body.text, p)


class DecisionIn(BaseModel):
    decision: str | None = Field(default=None, pattern="^(confirm|reject)$")
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/findings/{fid}/decision")
def finding_decide(fid: int, body: DecisionIn, request: Request, p: Principal = Depends(require_user("operator"))):
    st = _st(request)
    _finding_or_404(st, fid, p)
    return st.findings.decide(fid, body.decision, body.comment, p)


class VerifyIn(BaseModel):
    result: str | None = Field(default=None, pattern="^(agree|disagree)$")
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/findings/{fid}/verify")
def finding_verify(fid: int, body: VerifyIn, request: Request, p: Principal = Depends(require_user("supervisor"))):
    st = _st(request)
    f = _finding_or_404(st, fid, p)
    if body.result and f.get("decision") is None:
        raise HTTPException(status_code=409, detail="Сначала нужно решение оператора")
    return st.findings.verify(fid, body.result, body.comment, p)


@router.delete("/findings/{fid}")
def finding_delete(fid: int, request: Request, p: Principal = Depends(require_user("admin"))):
    if not _st(request).findings.delete(fid, p):
        raise HTTPException(status_code=404, detail="Находка не найдена")
    return {"ok": True}


@router.get("/findings/{fid}/frames/{n}.jpg")
def finding_frame(fid: int, n: int, request: Request, p: Principal = Depends(ui_access)):
    f = _finding_or_404(_st(request), fid, p)
    path = Path(f.get("frames_dir") or "") / f"{n:05d}.jpg"
    if not f.get("frames_dir") or not path.exists():
        raise HTTPException(status_code=404, detail="Кадр не найден")
    return FileResponse(str(path), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/findings/{fid}/clip.mp4")
def finding_clip(fid: int, request: Request, p: Principal = Depends(ui_access)):
    f = _finding_or_404(_st(request), fid, p)
    if not f.get("clip_path") or not Path(f["clip_path"]).exists():
        raise HTTPException(status_code=404, detail="Фрагмент не найден")
    return FileResponse(f["clip_path"], media_type="video/mp4", filename=f"finding_{fid}.mp4",
                        content_disposition_type="inline")
