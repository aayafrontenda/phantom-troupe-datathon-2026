"""Job lifecycle: create -> queue -> run -> finalize. Results are validated against the jury schema."""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .config import get_settings
from .db import Database, loads
from .events import EventBus
from .storage import Upload, place_upload
from .worker import PRIORITY_JURY, PRIORITY_UI, Outcome, WorkerPool

log = logging.getLogger("backend.jobs")

PUBLIC_STATUS = {"queued": "processing", "running": "processing", "done": "done", "failed": "failed"}
NO_RESULT = {"verdict": "no_violation", "violations": []}


class JobService:
    def __init__(self, db: Database, pool: WorkerPool, bus: EventBus,
                 on_result: Callable[[dict, dict], None] | None = None, findings=None):
        self.db = db
        self.pool = pool
        self.bus = bus
        self.on_result = on_result            # (job_row, result) -> alerts / clips
        self.findings = findings
        self._progress_ts: dict[str, float] = {}
        self._lock = threading.Lock()
        self.analyzer_version = get_settings().analyzer

    # ------------------------------------------------------------------ create
    def create(self, up: Upload, source: str, request_started_at: float | None = None,
               principal: str | None = None) -> dict:
        s = get_settings()
        now = time.time()
        job_id = uuid.uuid4().hex[:12]
        path = place_upload(up, job_id)
        req_start = request_started_at or now
        deadline = req_start + s.job_hard_limit_sec
        priority = PRIORITY_JURY if source == "jury" else PRIORITY_UI
        row = {
            "job_id": job_id, "status": "queued", "stage": "queued", "progress": 0.0, "priority": priority,
            "source": source, "filename": up.filename, "sha256": up.sha256, "size_bytes": up.size,
            "duration_sec": round(up.duration_sec, 2), "upload_path": str(path), "analyzer": self.analyzer_version,
            "request_started_at": req_start, "created_at": now, "deadline_at": deadline, "updated_at": now,
            "created_by": principal,
        }
        dup = self._find_duplicate(up.sha256) if s.dedup else None
        if dup is not None:
            result = self.load_result(dup["job_id"])
            if result is not None:
                row.update(status="done", stage="done", progress=1.0, started_at=now, finished_at=now,
                           dedup_of=dup["job_id"], verdict=result.get("verdict"),
                           n_violations=len(result.get("violations") or []), partial=dup.get("partial", 0),
                           result_path=dup["result_path"])
                self.db.insert("jobs", row)
                self.db.audit("job.dedup", principal, job_id, {"of": dup["job_id"], "source": source})
                log.info("job %s: identical to %s (sha256 match) -> instant result", job_id, dup["job_id"])
                if self.findings is not None:
                    self.findings.from_job(row, result)
                self.bus.publish(f"job:{job_id}", {"type": "done", "job_id": job_id})
                return row
        self.db.insert("jobs", row)
        self.db.audit("job.create", principal, job_id, {"source": source, "filename": up.filename, "bytes": up.size})
        self.pool.submit(job_id, str(path), priority, deadline)
        self.bus.publish(f"job:{job_id}", {"type": "queued", "job_id": job_id})
        return row

    def _find_duplicate(self, sha256: str) -> dict | None:
        return self.db.one("SELECT job_id, result_path, partial FROM jobs WHERE sha256=? AND status='done' "
                           "AND result_path IS NOT NULL AND analyzer=? AND partial=0 ORDER BY finished_at DESC LIMIT 1",
                           (sha256, self.analyzer_version))

    # ------------------------------------------------------------------ read
    def get(self, job_id: str) -> dict | None:
        return self.db.one("SELECT * FROM jobs WHERE job_id=?", (job_id,))

    def list(self, limit: int = 50, source: str | None = None) -> list[dict]:
        where = "WHERE source=?" if source else ""
        rows = self.db.all("SELECT job_id, status, stage, progress, source, filename, duration_sec, verdict, "
                           f"n_violations, partial, error, created_at, finished_at, request_started_at, created_by FROM jobs {where} "
                           "ORDER BY created_at DESC LIMIT ?", ((source, limit) if source else (limit,)))
        for r in rows:
            r["public_status"] = PUBLIC_STATUS.get(r["status"], r["status"])
            if r["status"] in ("queued", "running"):
                r["queue_position"] = self.pool.position(r["job_id"])
            if r.get("finished_at"):
                r["processing_sec"] = round(r["finished_at"] - (r.get("request_started_at") or r["created_at"]), 1)
            dec = self.decisions(r["job_id"])
            r["confirmed"] = sum(1 for v in dec.values() if v == "confirm")
            r["rejected"] = sum(1 for v in dec.values() if v in ("reject", "wrong_type"))
            r["reviewed"] = r["confirmed"] + r["rejected"]
        return rows

    def decisions(self, job_id: str) -> dict[int, str]:
        """Operator decision per violation index (from the findings table)."""
        return {int(r["violation_index"]): r["decision"] for r in self.db.all(
            "SELECT violation_index, decision FROM findings WHERE job_id=? AND decision IS NOT NULL", (job_id,))}

    def delete(self, job_id: str, actor: str | None = None) -> bool:
        """Cancel (if active) and remove a job with its video, result, clips, findings, alerts and events."""
        job = self.get(job_id)
        if job is None:
            return False
        if job["status"] in ("queued", "running"):
            self.pool.abort(job_id)
        s = get_settings()
        for p in (job.get("upload_path"), job.get("result_path") if not self._shared_result(job) else None):
            if p:
                Path(p).unlink(missing_ok=True)
        import shutil
        shutil.rmtree(s.evidence_dir / job_id, ignore_errors=True)
        alert_ids = [r["id"] for r in self.db.all("SELECT id FROM alerts WHERE job_id=?", (job_id,))]
        if self.findings is not None:
            self.findings.delete_for_job(job_id)
        with self.db.tx() as t:
            for aid in alert_ids:
                t.execute("DELETE FROM alert_deliveries WHERE alert_id=?", (aid,))
            t.execute("DELETE FROM alerts WHERE job_id=?", (job_id,))
            t.execute("DELETE FROM events WHERE job_id=?", (job_id,))
            t.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
        self.db.audit("job.delete", actor, job_id, {"filename": job.get("filename"), "status": job["status"]})
        self.bus.publish(f"job:{job_id}", {"type": "deleted", "job_id": job_id})
        self.bus.publish("jobs", {"type": "deleted", "job_id": job_id})
        log.info("job %s deleted by %s (was %s)", job_id, actor, job["status"])
        return True

    def _shared_result(self, job: dict) -> bool:
        """A dedup copy and its original share one result file: keep it while someone else points to it."""
        rp = job.get("result_path")
        if not rp:
            return False
        other = self.db.one("SELECT 1 AS x FROM jobs WHERE result_path=? AND job_id<>? LIMIT 1", (rp, job["job_id"]))
        return other is not None

    def load_result(self, job_id: str) -> dict | None:
        row = self.get(job_id)
        if not row or not row.get("result_path"):
            return None
        p = Path(row["result_path"])
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            log.exception("job %s: unreadable result %s", job_id, p)
            return None

    def public_view(self, job: dict, extras: bool = True) -> dict:
        """GET /jobs/{id}: mandatory fields first (job_id, status, verdict, violations), then extras."""
        status = PUBLIC_STATUS.get(job["status"], job["status"])
        out: dict[str, Any] = {"job_id": job["job_id"], "status": status}
        result = self.load_result(job["job_id"]) if job["status"] == "done" else None
        if job["status"] == "done":
            result = result or NO_RESULT
            out["verdict"] = result.get("verdict")
            out["violations"] = result.get("violations", [])
        if not extras:
            return out
        out["stage"] = job.get("stage")
        out["progress"] = round(float(job.get("progress") or 0.0), 2)
        if job["status"] in ("queued", "running"):
            pos = self.pool.position(job["job_id"])
            out["queue_position"] = pos if pos is not None else 0
            out["eta_sec"] = self._eta(job, pos)
        if job["status"] == "done" and result:
            out["timeline"] = result.get("timeline")
            out["meta"] = result.get("meta")
        if job.get("partial"):
            out["partial"] = True
        if job.get("dedup_of"):
            out["dedup_of"] = job["dedup_of"]
        if job.get("warning"):
            out["warning"] = job["warning"]
        if job.get("error"):
            out["error"] = job["error"]
        if job.get("finished_at"):
            out["processing_sec"] = round(job["finished_at"] - (job.get("request_started_at") or job["created_at"]), 1)
        out["filename"] = job.get("filename")
        out["duration_sec"] = job.get("duration_sec")
        out["created_at"] = job.get("created_at")
        out["created_by"] = job.get("created_by")
        out["source"] = job.get("source")
        out["analyzer"] = job.get("analyzer")
        return out

    def _eta(self, job: dict, pos: int | None) -> int | None:
        avg = self.db.one("SELECT AVG(finished_at - started_at) AS a FROM jobs WHERE status='done' "
                          "AND started_at IS NOT NULL AND dedup_of IS NULL AND finished_at > ?", (time.time() - 86400,))
        per_job = (avg or {}).get("a") or 60.0
        if job["status"] == "running":
            remaining = per_job * (1.0 - float(job.get("progress") or 0.0))
            return int(max(1.0, remaining))
        return int(per_job * ((pos or 0) + 1))

    # ------------------------------------------------------------------ worker callbacks
    def on_progress(self, job_id: str, stage: str, progress: float) -> None:
        now = time.time()
        with self._lock:
            last = self._progress_ts.get(job_id, 0.0)
            job = self.get(job_id)
            if job is None:
                return
            stage_changed = job.get("stage") != stage
            if not stage_changed and now - last < 0.5:
                return
            self._progress_ts[job_id] = now
        fields = {"stage": stage, "progress": float(progress), "updated_at": now}
        if job["status"] == "queued":
            fields.update(status="running", started_at=now)
        self.db.update("jobs", "job_id", job_id, fields)
        self.bus.publish(f"job:{job_id}", {"type": "progress", "job_id": job_id, "stage": stage,
                                           "progress": round(float(progress), 3)})

    def on_finish(self, o: Outcome) -> None:
        job = self.get(o.job_id)
        if job is None:
            return
        now = time.time()
        s = get_settings()
        self._progress_ts.pop(o.job_id, None)
        fields: dict[str, Any] = {"finished_at": now, "updated_at": now, "attempts": o.attempts}
        if job.get("started_at") is None:
            fields["started_at"] = now - o.duration_sec
        result: dict | None = None
        if o.kind == "done" and o.result is not None:
            result = o.result
        elif o.partial is not None:
            result = o.partial
            fields["partial"] = 1
            fields["warning"] = f"{o.kind}: {o.error}; returned partial result"
        elif o.kind in ("deadline", "stall", "crash") and s.on_deadline == "partial":
            result = dict(NO_RESULT)
            fields["partial"] = 1
            fields["warning"] = f"{o.kind}: {o.error}; no findings before the deadline"
        elif o.kind == "failed" and s.on_failure == "partial":
            result = dict(NO_RESULT)
            fields["partial"] = 1
            fields["warning"] = f"analyzer error: {o.error}; returned empty result"
        if result is None:
            fields.update(status="failed", stage="failed", error=(o.error or o.kind)[:500])
            self.db.update("jobs", "job_id", o.job_id, fields)
            log.error("job %s FAILED (%s, %s, %.1fs): %s", o.job_id, o.kind, o.worker, o.duration_sec, o.error)
            self.bus.publish(f"job:{o.job_id}", {"type": "failed", "job_id": o.job_id, "error": fields["error"]})
            return
        result, problems = sanitize_result(result, job)
        if problems:
            log.warning("job %s: result sanitized: %s", o.job_id, problems)
            fields["warning"] = ((fields.get("warning") or "") + f"; schema fixes: {problems}").strip("; ")
        result.setdefault("meta", {})
        if isinstance(result["meta"], dict):
            result["meta"].update(analyzer=job.get("analyzer"), worker=o.worker, attempts=o.attempts,
                                  partial=bool(fields.get("partial")), service_version=s.version)
        path = s.results_dir / f"{o.job_id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        fields.update(status="done", stage="done", progress=1.0, result_path=str(path),
                      verdict=result.get("verdict"), n_violations=len(result.get("violations") or []))
        self.db.update("jobs", "job_id", o.job_id, fields)
        total = now - (job.get("request_started_at") or job["created_at"])
        log.info("job %s done: %s, %d violation(s), %.1fs analysis, %.1fs total, worker=%s%s",
                 o.job_id, result.get("verdict"), fields["n_violations"], o.duration_sec, total, o.worker,
                 " [PARTIAL]" if fields.get("partial") else "")
        self.bus.publish(f"job:{o.job_id}", {"type": "done", "job_id": o.job_id, "verdict": result.get("verdict"),
                                             "n_violations": fields["n_violations"]})
        if self.on_result is not None:
            try:
                self.on_result({**job, **fields}, result)
            except Exception:
                log.exception("job %s: post-processing failed", o.job_id)

    # ------------------------------------------------------------------ recovery
    def recover(self) -> int:
        """Re-queue jobs interrupted by a restart; fail those whose video is gone."""
        n = 0
        now = time.time()
        for job in self.db.all("SELECT * FROM jobs WHERE status IN ('queued','running')"):
            path = job.get("upload_path") or ""
            if Path(path).exists():
                self.db.update("jobs", "job_id", job["job_id"],
                               {"status": "queued", "stage": "queued", "progress": 0.0, "updated_at": now})
                self.pool.submit(job["job_id"], path, int(job.get("priority") or PRIORITY_UI),
                                 float(job.get("deadline_at") or now + get_settings().job_hard_limit_sec),
                                 attempts=int(job.get("attempts") or 0))
                n += 1
            else:
                self.db.update("jobs", "job_id", job["job_id"],
                               {"status": "failed", "stage": "failed", "error": "service restarted, video not found",
                                "finished_at": now, "updated_at": now})
        if n:
            log.info("recovered %d interrupted job(s)", n)
        return n

    def stats(self) -> dict:
        row = self.db.one("SELECT COUNT(*) AS total, "
                          "SUM(status='done') AS done, SUM(status='failed') AS failed, "
                          "SUM(status IN ('queued','running')) AS active, "
                          "SUM(verdict='violation') AS violations, SUM(partial) AS partial, "
                          "AVG(CASE WHEN status='done' AND dedup_of IS NULL THEN finished_at - request_started_at END) AS avg_total_sec, "
                          "MAX(CASE WHEN status='done' AND dedup_of IS NULL THEN finished_at - request_started_at END) AS max_total_sec "
                          "FROM jobs") or {}
        return {k: (round(v, 1) if isinstance(v, float) else (v or 0)) for k, v in row.items()}


# ---------------------------------------------------------------------------- result hygiene

def sanitize_result(result: dict, job: dict) -> tuple[dict, list[str]]:
    """Never ship an invalid jury response: fix what can be fixed, report what was fixed."""
    problems: list[str] = []
    res = dict(result) if isinstance(result, dict) else {}
    viols_in = res.get("violations")
    if not isinstance(viols_in, list):
        problems.append("violations was not a list")
        viols_in = []
    viols: list[dict] = []
    for i, v in enumerate(viols_in):
        if not isinstance(v, dict):
            problems.append(f"violations[{i}] dropped: not an object")
            continue
        v = dict(v)
        t = v.get("type")
        if not isinstance(t, str) or not t.strip():
            v["type"] = "Признаки возможного нарушения кассовой дисциплины"
            problems.append(f"violations[{i}].type filled")
        try:
            v["timecode_sec"] = round(float(v.get("timecode_sec")), 1)
        except (TypeError, ValueError):
            v["timecode_sec"] = 0.0
            problems.append(f"violations[{i}].timecode_sec set to 0")
        d = v.get("description")
        if not isinstance(d, str) or not d.strip():
            v["description"] = "На видео зафиксировано действие, которое может указывать на нарушение; требуется проверка."
            problems.append(f"violations[{i}].description filled")
        frames = v.get("evidence_frames")
        good: list[dict] = []
        if isinstance(frames, list):
            for f in frames:
                if isinstance(f, dict) and isinstance(f.get("image_base64"), str) and _looks_jpeg(f["image_base64"]):
                    try:
                        ts = round(float(f.get("timestamp_sec", v["timecode_sec"])), 2)
                    except (TypeError, ValueError):
                        ts = v["timecode_sec"]
                    good.append({**f, "timestamp_sec": ts})
        if not good:
            frame = _extract_frame(job.get("upload_path"), v["timecode_sec"], job.get("duration_sec"))
            if frame:
                good = [frame]
                problems.append(f"violations[{i}].evidence_frames re-extracted")
            else:
                problems.append(f"violations[{i}] dropped: no evidence frame")
                continue
        if len(good) > 3:
            good = sorted(good, key=lambda f: abs(f["timestamp_sec"] - v["timecode_sec"]))[:3]
            good.sort(key=lambda f: f["timestamp_sec"])
            problems.append(f"violations[{i}].evidence_frames trimmed to 3")
        v["evidence_frames"] = good
        viols.append(v)
    viols.sort(key=lambda x: x["timecode_sec"])
    res["violations"] = viols
    verdict = "violation" if viols else "no_violation"
    if res.get("verdict") != verdict:
        if res.get("verdict") in ("violation", "no_violation"):
            problems.append(f"verdict {res.get('verdict')} -> {verdict}")
        res["verdict"] = verdict
    ordered = {"verdict": res["verdict"], "violations": res["violations"]}
    for k, v in res.items():
        if k not in ordered:
            ordered[k] = v
    return ordered, problems


def _looks_jpeg(b64: str) -> bool:
    try:
        head = base64.b64decode(b64[:64] + "=" * (-len(b64[:64]) % 4))
        return head.startswith(b"\xff\xd8")
    except Exception:
        return False


def _extract_frame(path: str | None, t: float, duration: float | None = None) -> dict | None:
    if not path or not Path(path).exists():
        return None
    try:
        from ml.video import frame_at, to_jpeg_b64
        if duration:
            t = min(float(t), max(0.0, float(duration) - 0.1))
        for cand in (t, t - 0.5, 0.0):
            cand = max(0.0, cand)
            img = frame_at(path, cand)
            if img is not None:
                return {"timestamp_sec": round(cand, 2), "image_base64": to_jpeg_b64(img)}
        return None
    except Exception:
        log.exception("frame extraction failed for %s @ %.1f", path, t)
        return None


def load_json(v: str | None) -> Any:
    return loads(v)
