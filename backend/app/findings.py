"""Findings: one record per possible violation, from an uploaded video or a live camera.

Workflow: AI description -> operator may reword it and decides confirm / reject -> supervisor verifies the
operator's decision (agree / disagree). Every step is kept in finding_history.
"""
from __future__ import annotations

import base64
import json
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .config import get_settings
from .db import Database, loads
from .events import EventBus

log = logging.getLogger("backend.findings")

DECISIONS = {"confirm", "reject"}
VERIFY_RESULTS = {"agree", "disagree"}
LIST_COLUMNS = ("id, source, job_id, violation_index, camera_id, camera_name, alert_id, type_code, type_name, t_sec, "
                "confidence, description_ai, description_edit, decision, decided_by, decided_at, decision_comment, "
                "verified, verify_result, verified_by, verified_at, verify_comment, created_at, updated_at")


class FindingService:
    def __init__(self, db: Database, bus: EventBus, alerts=None, quality=None):
        self.db = db
        self.bus = bus
        self.alerts = alerts
        self.quality = quality
        self.on_decided = None   # (finding, actor) -> None; the Telegram bot asks supervisors to verify rejections
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ create
    def from_job(self, job: dict, result: dict) -> list[dict]:
        """Create findings for a finished check (idempotent per job + violation index)."""
        out = []
        now = time.time()
        for i, v in enumerate(result.get("violations") or []):
            if self.db.one("SELECT id FROM findings WHERE job_id=? AND violation_index=?", (job["job_id"], i)):
                continue
            fid = self.db.insert("findings", {
                "source": "upload", "job_id": job["job_id"], "violation_index": i,
                "type_code": v.get("type_code") or "T99", "type_name": v.get("type"),
                "t_sec": v.get("timecode_sec"), "confidence": v.get("confidence"),
                "description_ai": v.get("description"), "rule": v.get("rule") or {},
                "created_at": now, "updated_at": now})
            out.append(self.get(fid))
        if out:
            self.bus.publish("findings", {"type": "finding", "findings": [self._brief(f) for f in out]})
        return out

    def from_camera(self, alert: dict, camera: dict, frames: list[tuple[float, bytes]], alert_ts: float) -> dict | None:
        """A camera alert with the frames around it: frames to disk, an mp4 if ffmpeg is present, one finding."""
        s = get_settings()
        now = time.time()
        code = alert.get("type_code") or "T99"
        with self._lock:
            fid = self.db.insert("findings", {
                "source": "camera", "camera_id": camera["id"], "camera_name": camera["name"], "alert_id": alert.get("id"),
                "type_code": code, "type_name": alert.get("type_name"), "t_sec": None, "confidence": alert.get("confidence"),
                "description_ai": _camera_description(code, alert.get("message")), "rule": _camera_rule(code),
                "created_at": now, "updated_at": now})
        fdir = s.evidence_dir / "camera" / str(fid)
        fdir.mkdir(parents=True, exist_ok=True)
        frames = sorted(frames, key=lambda f: f[0])
        index = []
        for n, (ts, jpeg) in enumerate(frames):
            (fdir / f"{n:05d}.jpg").write_bytes(jpeg)
            index.append({"n": n, "ts": round(ts, 3)})
        t0 = frames[0][0] if frames else alert_ts
        t_sec = round(max(0.0, alert_ts - t0), 2)
        (fdir / "frames.json").write_text(json.dumps({"t0": t0, "alert_ts": alert_ts, "frames": index}), encoding="utf-8")
        clip = _encode_clip(fdir, frames)
        self.db.update("findings", "id", fid, {"frames_dir": str(fdir), "clip_path": str(clip) if clip else None,
                                                "t_sec": t_sec, "updated_at": time.time()})
        f = self.get(fid)
        self.bus.publish("findings", {"type": "finding", "findings": [self._brief(f)]})
        log.info("finding #%d from camera %s (%s): %d frames%s", fid, camera["id"], code, len(frames),
                 ", clip" if clip else "")
        return f

    # ------------------------------------------------------------------ read
    def get(self, fid: int, with_frames: bool = False) -> dict | None:
        r = self.db.one("SELECT * FROM findings WHERE id=?", (fid,))
        if r is None:
            return None
        r["rule"] = loads(r.get("rule"), {})
        r["verified"] = bool(r["verified"])
        r["description"] = r["description_edit"] or r["description_ai"]
        self._enrich([r])
        if with_frames:
            r["frames"] = self.frames(r)
            r.update(self._media(r))
        return r

    def _brief(self, f: dict) -> dict:
        return {k: f.get(k) for k in ("id", "source", "job_id", "camera_id", "camera_name", "type_code", "type_name",
                                      "t_sec", "confidence", "decision", "verified", "created_at")}

    def frames(self, f: dict) -> list[dict]:
        """Up to three key frames as base64 JPEG (uploads: from the result file; cameras: from disk)."""
        if f["source"] == "upload":
            res = self._result(f["job_id"])
            viols = (res or {}).get("violations") or []
            i = f.get("violation_index")
            if i is not None and 0 <= i < len(viols):
                return [{"timestamp_sec": fr.get("timestamp_sec"), "image_base64": fr.get("image_base64")}
                        for fr in viols[i].get("evidence_frames") or []]
            return []
        fdir = Path(f.get("frames_dir") or "")
        meta = loads((fdir / "frames.json").read_text(encoding="utf-8"), {}) if (fdir / "frames.json").exists() else {}
        index = meta.get("frames") or []
        if not index:
            return []
        t0 = meta.get("t0") or 0.0
        at = meta.get("alert_ts") or t0
        key = min(index, key=lambda x: abs(x["ts"] - at))
        picks = {key["n"]}
        for dt in (-1.0, 1.0):
            near = min(index, key=lambda x: abs(x["ts"] - (at + dt)))
            picks.add(near["n"])
        out = []
        for n in sorted(picks):
            p = fdir / f"{n:05d}.jpg"
            if p.exists():
                out.append({"timestamp_sec": round(index[n]["ts"] - t0, 2),
                            "image_base64": base64.b64encode(p.read_bytes()).decode("ascii")})
        return out

    def frame_sequence(self, f: dict) -> list[dict]:
        fdir = Path(f.get("frames_dir") or "")
        meta = loads((fdir / "frames.json").read_text(encoding="utf-8"), {}) if (fdir / "frames.json").exists() else {}
        t0 = meta.get("t0") or 0.0
        return [{"n": x["n"], "t": round(x["ts"] - t0, 3), "url": f"/ui/api/findings/{f['id']}/frames/{x['n']}.jpg"}
                for x in meta.get("frames") or []]

    def _media(self, f: dict) -> dict:
        s = get_settings()
        if f["source"] == "upload":
            job = self.db.one("SELECT upload_path, duration_sec, filename, dedup_of FROM jobs WHERE job_id=?", (f["job_id"],)) or {}
            owner = job.get("dedup_of") or f["job_id"]
            clip = s.evidence_dir / owner / f"violation_{f.get('violation_index')}.mp4"
            avail = bool(job.get("upload_path") and Path(job["upload_path"]).exists())
            return {"video_url": f"/ui/api/jobs/{f['job_id']}/video" if avail else None,
                    "clip_url": f"/ui/api/jobs/{f['job_id']}/violations/{f.get('violation_index')}/clip.mp4" if clip.exists() else None,
                    "duration_sec": job.get("duration_sec"), "filename": job.get("filename"), "sequence": []}
        seq = self.frame_sequence(f)
        return {"video_url": None, "clip_url": f"/ui/api/findings/{f['id']}/clip.mp4" if f.get("clip_path") and Path(f["clip_path"]).exists() else None,
                "duration_sec": seq[-1]["t"] if seq else None, "filename": None, "sequence": seq}

    def _result(self, job_id: str) -> dict | None:
        job = self.db.one("SELECT result_path FROM jobs WHERE job_id=?", (job_id,))
        if not job or not job.get("result_path") or not Path(job["result_path"]).exists():
            return None
        try:
            return json.loads(Path(job["result_path"]).read_text(encoding="utf-8"))
        except Exception:
            return None

    def user_names(self) -> dict[str, str]:
        return {u["login"]: u["name"] for u in self.db.all("SELECT login, name FROM users")}

    def _enrich(self, rows: list[dict], names: dict[str, str] | None = None) -> list[dict]:
        names = names if names is not None else self.user_names()
        for r in rows:
            r["verified"] = bool(r["verified"])
            r["edited"] = bool(r["description_edit"])
            r["decided_by_name"] = names.get(r.get("decided_by") or "", r.get("decided_by"))
            r["verified_by_name"] = names.get(r.get("verified_by") or "", r.get("verified_by"))
            r["below_threshold"] = bool(self.quality and self.quality.below_threshold(r.get("type_code"), r.get("confidence")))
        return rows

    def for_job(self, job_id: str) -> list[dict]:
        rows = self.db.all(f"SELECT {LIST_COLUMNS} FROM findings WHERE job_id=? ORDER BY violation_index", (job_id,))
        return self._enrich(rows)

    def decisions_for_job(self, job_id: str) -> dict[int, str]:
        return {int(r["violation_index"]): r["decision"] for r in self.db.all(
            "SELECT violation_index, decision FROM findings WHERE job_id=? AND decision IS NOT NULL", (job_id,))}

    def list(self, *, source: str | None = None, decision: str | None = None, verified: bool | None = None,
             type_code: str | None = None, camera_id: str | None = None, camera_ids: list[str] | None = None,
             decided_by: str | None = None, edited: bool | None = None, since: float | None = None,
             until: float | None = None, q: str | None = None, limit: int = 100, offset: int = 0) -> dict:
        conds, params = [], []
        if source:
            conds.append("source=?"); params.append(source)
        if decision == "pending":
            conds.append("decision IS NULL")
        elif decision in DECISIONS:
            conds.append("decision=?"); params.append(decision)
        elif decision == "decided":
            conds.append("decision IS NOT NULL")
        if verified is not None:
            conds.append("verified=?"); params.append(int(verified))
        if type_code:
            conds.append("type_code=?"); params.append(type_code)
        if camera_id:
            conds.append("camera_id=?"); params.append(camera_id)
        if camera_ids is not None:
            marks = ",".join("?" for _ in camera_ids) or "''"
            conds.append(f"(source<>'camera' OR camera_id IN ({marks}))"); params.extend(camera_ids)
        if decided_by:
            conds.append("decided_by=?"); params.append(decided_by)
        if edited is not None:
            conds.append("description_edit IS NOT NULL" if edited else "description_edit IS NULL")
        if since:
            conds.append("created_at>=?"); params.append(since)
        if until:
            conds.append("created_at<=?"); params.append(until)
        if q:
            conds.append("(camera_name LIKE ? OR type_name LIKE ? OR job_id IN (SELECT job_id FROM jobs WHERE filename LIKE ?))")
            params.extend([f"%{q}%"] * 3)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        total = (self.db.one(f"SELECT COUNT(*) AS n FROM findings{where}", params) or {}).get("n", 0)
        rows = self.db.all(f"SELECT {LIST_COLUMNS} FROM findings{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                           params + [limit, offset])
        names = self._filenames([r["job_id"] for r in rows if r.get("job_id")])
        self._enrich(rows)
        for r in rows:
            r["filename"] = names.get(r["job_id"])
        return {"findings": rows, "total": total}

    def _filenames(self, job_ids: list[str]) -> dict[str, str]:
        ids = sorted(set(job_ids))
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        return {j["job_id"]: j["filename"] for j in self.db.all(f"SELECT job_id, filename FROM jobs WHERE job_id IN ({marks})", ids)}

    def counts(self, camera_ids: list[str] | None = None) -> dict:
        scope, params = "", []
        if camera_ids is not None:
            marks = ",".join("?" for _ in camera_ids) or "''"
            scope = f" WHERE (source<>'camera' OR camera_id IN ({marks}))"
            params = list(camera_ids)
        r = self.db.one("SELECT COUNT(*) AS total, SUM(decision IS NULL) AS pending, "
                        "SUM(decision='confirm') AS confirmed, SUM(decision='reject') AS rejected, "
                        "SUM(decision IS NOT NULL AND verified=0) AS to_verify, "
                        "SUM(decision='reject' AND verified=0) AS rejected_unverified, "
                        "SUM(verified=1) AS verified, SUM(verify_result='disagree') AS disagreed, "
                        "SUM(description_edit IS NOT NULL) AS edited "
                        f"FROM findings{scope}", params) or {}
        return {k: int(v or 0) for k, v in r.items()}

    def history(self, fid: int) -> list[dict]:
        rows = self.db.all("SELECT id, actor, actor_role, action, payload, created_at FROM finding_history "
                           "WHERE finding_id=? ORDER BY id", (fid,))
        for r in rows:
            r["payload"] = loads(r.get("payload"), {})
        return rows

    # ------------------------------------------------------------------ write
    def _log(self, fid: int, actor, action: str, payload: dict | None = None) -> None:
        self.db.insert("finding_history", {"finding_id": fid, "actor": actor.name, "actor_role": actor.role,
                                           "action": action, "payload": payload or {}, "created_at": time.time()})

    def edit(self, fid: int, text: str | None, actor) -> dict | None:
        f = self.get(fid)
        if f is None:
            return None
        text = (text or "").strip()[:2000]
        new = text if text and text != (f["description_ai"] or "").strip() else None
        if new == f.get("description_edit"):
            return f
        self.db.update("findings", "id", fid, {"description_edit": new, "updated_at": time.time()})
        self._log(fid, actor, "edit", {"before": f.get("description_edit"), "after": new})
        self.db.audit("finding.edit", actor.name, str(fid))
        return self._changed(fid)

    def decide(self, fid: int, decision: str | None, comment: str | None, actor) -> dict | None:
        f = self.get(fid)
        if f is None:
            return None
        if decision is not None and decision not in DECISIONS:
            raise ValueError(f"bad decision {decision!r}")
        now = time.time()
        fields: dict[str, Any] = {"updated_at": now}
        if decision is None:
            fields.update(decision=None, decided_by=None, decided_at=None, decision_comment=None,
                          verified=0, verify_result=None, verified_by=None, verified_at=None, verify_comment=None)
            action = "undo"
        else:
            fields.update(decision=decision, decided_by=actor.name, decided_at=now,
                          decision_comment=(comment or "").strip()[:1000] or None)
            if f.get("decision") != decision:  # a changed decision needs a fresh verification
                fields.update(verified=0, verify_result=None, verified_by=None, verified_at=None, verify_comment=None)
            action = "decide"
        self.db.update("findings", "id", fid, fields)
        self._log(fid, actor, action, {"before": f.get("decision"), "after": decision, "comment": comment})
        self.db.audit("finding.decide", actor.name, str(fid), {"decision": decision})
        self._sync_alert(f, decision, actor.name)
        out = self._changed(fid)
        if self.on_decided is not None and decision is not None:
            try:
                self.on_decided(out, actor)
            except Exception:
                log.exception("finding #%s: on_decided hook failed", fid)
        return out

    def verify(self, fid: int, result: str | None, comment: str | None, actor) -> dict | None:
        f = self.get(fid)
        if f is None:
            return None
        if result is not None and result not in VERIFY_RESULTS:
            raise ValueError(f"bad verify result {result!r}")
        now = time.time()
        if result is None:
            fields = {"verified": 0, "verify_result": None, "verified_by": None, "verified_at": None,
                      "verify_comment": None, "updated_at": now}
            action = "unverify"
        else:
            fields = {"verified": 1, "verify_result": result, "verified_by": actor.name, "verified_at": now,
                      "verify_comment": (comment or "").strip()[:1000] or None, "updated_at": now}
            action = "verify"
        self.db.update("findings", "id", fid, fields)
        self._log(fid, actor, action, {"result": result, "comment": comment, "operator_decision": f.get("decision")})
        self.db.audit("finding.verify", actor.name, str(fid), {"result": result})
        return self._changed(fid)

    def _changed(self, fid: int) -> dict:
        if self.quality is not None:
            self.quality.invalidate()
        f = self.get(fid)
        self.bus.publish("findings", {"type": "finding_update", "findings": [self._brief(f)]})
        if f.get("job_id"):
            self.bus.publish(f"job:{f['job_id']}", {"type": "finding_update", "job_id": f["job_id"], "finding_id": fid})
        return f

    def _sync_alert(self, f: dict, decision: str | None, by: str) -> None:
        if self.alerts is None:
            return
        try:
            if f.get("alert_id"):
                if decision is None:
                    self.alerts.reopen(f["alert_id"])
                else:
                    self.alerts.ack(f["alert_id"], by=by, decision="resolved" if decision == "confirm" else "false_positive",
                                    comment="decision made on the finding page", record_feedback=False)
            elif f.get("job_id"):
                self.alerts.sync_review(f["job_id"], f.get("type_code"), f.get("t_sec"),
                                        decision or "clear", by)
        except Exception:
            log.exception("finding #%s: alert sync failed", f.get("id"))

    def delete_for_job(self, job_id: str) -> None:
        ids = [r["id"] for r in self.db.all("SELECT id FROM findings WHERE job_id=?", (job_id,))]
        with self.db.tx() as t:
            for fid in ids:
                t.execute("DELETE FROM finding_history WHERE finding_id=?", (fid,))
            t.execute("DELETE FROM findings WHERE job_id=?", (job_id,))

    def delete(self, fid: int, actor) -> bool:
        f = self.get(fid)
        if f is None:
            return False
        if f.get("frames_dir"):
            shutil.rmtree(f["frames_dir"], ignore_errors=True)
        with self.db.tx() as t:
            t.execute("DELETE FROM finding_history WHERE finding_id=?", (fid,))
            t.execute("DELETE FROM findings WHERE id=?", (fid,))
        self.db.audit("finding.delete", actor.name, str(fid))
        self.bus.publish("findings", {"type": "finding_deleted", "id": fid})
        return True

    def export_rows(self) -> list[dict]:
        rows = self.db.all(f"SELECT {LIST_COLUMNS} FROM findings ORDER BY id")
        names = self._filenames([r["job_id"] for r in rows if r.get("job_id")])
        for r in rows:
            r["filename"] = names.get(r["job_id"])
        return rows


# ---------------------------------------------------------------------------- helpers

def _camera_description(code: str, message: str | None) -> str:
    try:
        from ml import kb
        if code in kb.type_codes():
            return kb.build_description(code, message or "")
    except Exception:
        pass
    return message or ""


def _camera_rule(code: str) -> dict:
    try:
        from ml import kb
        if code in kb.type_codes():
            rule = kb.rule_of(code)
            return {"kind": rule.get("norm_kind", "direct"), "refs": kb.refs_struct(code), "caveat": rule.get("caveat")}
    except Exception:
        pass
    return {}


def _encode_clip(fdir: Path, frames: list[tuple[float, bytes]]) -> Path | None:
    if len(frames) < 2 or shutil.which("ffmpeg") is None:
        return None
    span = max(0.5, frames[-1][0] - frames[0][0])
    fps = max(1.0, min(30.0, (len(frames) - 1) / span))
    dst = fdir / "clip.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-framerate", f"{fps:.2f}", "-i", str(fdir / "%05d.jpg"),
           "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
    try:
        subprocess.run(cmd, check=True, timeout=60, capture_output=True)
        return dst
    except Exception as e:
        log.warning("clip encode failed in %s: %s", fdir, e)
        return None
