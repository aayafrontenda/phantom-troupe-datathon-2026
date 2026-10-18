from __future__ import annotations

import base64
import csv
import io
import json
import statistics
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from .config import Settings, get_settings
from .db import Database, loads

FINAL_SQL = ("CASE WHEN decision IS NULL THEN NULL "
             "WHEN verify_result='disagree' THEN (decision='reject') ELSE (decision='confirm') END")
THRESHOLD_STEPS = [round(0.5 + 0.05 * i, 2) for i in range(1, 9)]
WEEKS = 8
CACHE_SEC = 30


def final_label(row: dict) -> bool | None:
    if not row.get("decision"):
        return None
    is_violation = row["decision"] == "confirm"
    if row.get("verify_result") == "disagree":
        is_violation = not is_violation
    return is_violation


class QualityService:
    def __init__(self, db: Database, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        self._lock = threading.Lock()
        self._thresholds: dict[str, dict] | None = None
        self._thresholds_at = 0.0

    def invalidate(self) -> None:
        with self._lock:
            self._thresholds = None

    def thresholds(self) -> dict[str, dict]:
        with self._lock:
            if self._thresholds is not None and time.time() - self._thresholds_at < CACHE_SEC:
                return self._thresholds
        rows = self.db.all(f"SELECT type_code, confidence, {FINAL_SQL} AS violation FROM findings "
                           "WHERE decision IS NOT NULL AND confidence IS NOT NULL")
        by_type: dict[str, list[tuple[float, bool]]] = {}
        for r in rows:
            by_type.setdefault(r["type_code"] or "T99", []).append((float(r["confidence"]), bool(r["violation"])))
        base = self.settings.quality_base_confidence
        target = self.settings.quality_target_precision
        need = self.settings.quality_min_samples
        out: dict[str, dict] = {}
        for code, samples in by_type.items():
            n = len(samples)
            prec = sum(1 for _, v in samples if v) / n
            info = {"base": base, "applied": base, "status": "few", "samples": n, "precision": round(prec, 3)}
            if n >= need:
                if prec >= target:
                    info["status"] = "ok"
                else:
                    info["status"] = "retrain"
                    for c in THRESHOLD_STEPS:
                        if c <= base:
                            continue
                        sub = [v for conf, v in samples if conf >= c]
                        if len(sub) >= 5 and sum(sub) / len(sub) >= target:
                            info.update(applied=c, status="raised", kept=len(sub))
                            break
            out[code] = info
        with self._lock:
            self._thresholds, self._thresholds_at = out, time.time()
        return out

    def threshold_for(self, type_code: str | None) -> float:
        info = self.thresholds().get(type_code or "T99")
        return float(info["applied"]) if info else self.settings.quality_base_confidence

    def below_threshold(self, type_code: str | None, confidence: float | None) -> bool:
        if confidence is None:
            return False
        info = self.thresholds().get(type_code or "T99")
        return bool(info and info["status"] == "raised" and float(confidence) < float(info["applied"]))

    def stats(self, days: int = 30, camera_ids: list[str] | None = None, camera_id: str | None = None) -> dict:
        now = time.time()
        since = now - days * 86400 if days > 0 else 0.0
        scope, params = self._scope(camera_ids, camera_id)
        cur = self._summary(since, now, scope, params)
        prev = self._summary(since - days * 86400, since, scope, params) if days > 0 else None
        if prev and prev["basis_n"] and cur["accuracy"] is not None and prev["accuracy"] is not None:
            cur["accuracy_delta_pp"] = round((cur["accuracy"] - prev["accuracy"]) * 100, 1)
        else:
            cur["accuracy_delta_pp"] = None
        thresholds = self.thresholds()
        return {
            "period": {"days": days, "since": since or None, "until": now},
            "summary": cur,
            "by_type": self._by_type(since, scope, params, thresholds),
            "weekly": self._weekly(scope, params),
            "operators": self._operators(since, scope, params),
            "thresholds": {"base": self.settings.quality_base_confidence, "target": self.settings.quality_target_precision,
                           "min_samples": self.settings.quality_min_samples,
                           "raised": sorted(c for c, t in thresholds.items() if t["status"] == "raised"),
                           "retrain": sorted(c for c, t in thresholds.items() if t["status"] == "retrain")},
            "dataset": self._dataset_summary(scope, params),
        }

    @staticmethod
    def _scope(camera_ids: list[str] | None, camera_id: str | None) -> tuple[str, list]:
        conds, params = [], []
        if camera_id:
            conds.append("camera_id=?"); params.append(camera_id)
        if camera_ids is not None:
            marks = ",".join("?" for _ in camera_ids) or "''"
            conds.append(f"(source<>'camera' OR camera_id IN ({marks}))"); params.extend(camera_ids)
        return (" AND " + " AND ".join(conds)) if conds else "", params

    def _summary(self, since: float, until: float, scope: str, params: list) -> dict:
        r = self.db.one(
            "SELECT COUNT(*) AS total, SUM(decision IS NOT NULL) AS decided, SUM(decision='confirm') AS confirmed, "
            "SUM(decision='reject') AS rejected, SUM(verified=1) AS verified, "
            "SUM(verify_result='disagree') AS disagreed, SUM(description_edit IS NOT NULL) AS edited, "
            "SUM(decision='reject' AND verify_result='disagree') AS flagged, "
            "SUM(decision='confirm' AND verify_result='disagree') AS overruled_confirm, "
            f"SUM(verified=1 AND ({FINAL_SQL})) AS true_verified, SUM(verified=1 AND NOT ({FINAL_SQL})) AS false_verified "
            f"FROM findings WHERE created_at>=? AND created_at<? {scope}", [since, until, *params]) or {}
        out = {k: int(v or 0) for k, v in r.items()}
        if out["verified"]:
            basis, basis_n, true_n = "verified", out["verified"], out["true_verified"]
        else:
            basis, basis_n, true_n = "operators", out["decided"], out["confirmed"]
        out.update(basis=basis, basis_n=basis_n,
                   accuracy=round(true_n / basis_n, 3) if basis_n else None,
                   coverage=round(out["verified"] / out["decided"], 3) if out["decided"] else None)
        return out

    def _by_type(self, since: float, scope: str, params: list, thresholds: dict[str, dict]) -> list[dict]:
        rows = self.db.all(
            "SELECT type_code, MAX(type_name) AS type_name, COUNT(*) AS total, SUM(decision IS NOT NULL) AS decided, "
            "SUM(decision='confirm') AS confirmed, SUM(decision='reject') AS rejected, SUM(verified=1) AS verified, "
            f"SUM(decision IS NOT NULL AND ({FINAL_SQL})) AS violations "
            f"FROM findings WHERE created_at>=? {scope} GROUP BY type_code", [since, *params])
        out = []
        for r in rows:
            d = {k: (int(v or 0) if k not in ("type_code", "type_name") else v) for k, v in r.items()}
            d["type_code"] = d["type_code"] or "T99"
            d["confirm_rate"] = round(d["violations"] / d["decided"], 3) if d["decided"] else None
            d["threshold"] = thresholds.get(d["type_code"], {"base": self.settings.quality_base_confidence,
                                                             "applied": self.settings.quality_base_confidence,
                                                             "status": "few", "samples": 0})
            out.append(d)
        out.sort(key=lambda x: (-(x["confirm_rate"] if x["confirm_rate"] is not None else -1), -x["decided"]))
        return out

    def _weekly(self, scope: str, params: list) -> list[dict]:
        today = datetime.now()
        monday = (today - timedelta(days=today.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        start = monday - timedelta(weeks=WEEKS - 1)
        rows = self.db.all(f"SELECT created_at, decision, verify_result, verified FROM findings "
                           f"WHERE created_at>=? AND decision IS NOT NULL {scope}", [start.timestamp(), *params])
        buckets = [{"week": (start + timedelta(weeks=i)).isocalendar()[1], "start": (start + timedelta(weeks=i)).timestamp(),
                    "decided": 0, "false": 0, "verified": 0} for i in range(WEEKS)]
        for r in rows:
            i = int((r["created_at"] - start.timestamp()) // (7 * 86400))
            if 0 <= i < WEEKS:
                b = buckets[i]
                b["decided"] += 1
                b["verified"] += int(bool(r["verified"]))
                if final_label(r) is False:
                    b["false"] += 1
        for b in buckets:
            b["rate"] = round(b["false"] / b["decided"], 3) if b["decided"] else None
        return buckets

    def _operators(self, since: float, scope: str, params: list) -> list[dict]:
        rows = self.db.all(
            "SELECT decided_by AS login, COUNT(*) AS decided, SUM(decision='reject') AS rejected, "
            "SUM(description_edit IS NOT NULL) AS edited, SUM(verified=1) AS verified, "
            "SUM(verify_result='disagree') AS disagreed, SUM(decision='reject' AND verify_result='disagree') AS flagged_rejects "
            f"FROM findings WHERE decision IS NOT NULL AND decided_by IS NOT NULL AND created_at>=? {scope} "
            "GROUP BY decided_by ORDER BY decided DESC", [since, *params])
        users = {u["login"]: u for u in self.db.all("SELECT login, name, role, camera_ids FROM users")}
        out = []
        for r in rows:
            d = {k: (int(v or 0) if k != "login" else v) for k, v in r.items()}
            u = users.get(d["login"], {})
            d["name"] = u.get("name") or d["login"]
            d["role"] = u.get("role")
            d["cameras"] = loads(u.get("camera_ids"), []) if u else []
            d["reject_rate"] = round(d["rejected"] / d["decided"], 3) if d["decided"] else None
            d["coverage"] = round(d["verified"] / d["decided"], 3) if d["decided"] else None
            d["disagree_rate"] = round(d["disagreed"] / d["verified"], 3) if d["verified"] else None
            out.append(d)
        rates = [d["reject_rate"] for d in out if d["reject_rate"] is not None and d["decided"] >= 5]
        median = statistics.median(rates) if rates else 0.0
        for d in out:
            many_disagreements = d["disagreed"] >= 3 and (d["disagree_rate"] or 0) >= 0.05
            rejects_too_often = d["decided"] >= 20 and (d["reject_rate"] or 0) >= max(0.3, 2 * median)
            d["flagged"] = bool(many_disagreements or rejects_too_often)
            d["flag_reason"] = "disagree" if many_disagreements else "rejects" if rejects_too_often else None
        return out

    def _dataset_summary(self, scope: str, params: list) -> dict:
        r = self.db.one(
            "SELECT COUNT(*) AS examples, SUM(verified=1) AS verified, "
            f"SUM(NOT ({FINAL_SQL})) AS negatives, SUM({FINAL_SQL}) AS positives "
            f"FROM findings WHERE decision IS NOT NULL {scope} AND (job_id IS NULL OR job_id NOT IN "
            "(SELECT job_id FROM jobs WHERE source='jury'))", params) or {}
        return {k: int(v or 0) for k, v in r.items()}

    def dataset_rows(self, days: int = 0, camera_ids: list[str] | None = None) -> list[dict]:
        since = time.time() - days * 86400 if days > 0 else 0.0
        scope, params = self._scope(camera_ids, None)
        rows = self.db.all(
            "SELECT f.*, j.filename, j.result_path, j.source AS job_source FROM findings f "
            "LEFT JOIN jobs j ON j.job_id=f.job_id "
            f"WHERE f.decision IS NOT NULL AND f.created_at>=? {scope.replace('camera_id', 'f.camera_id').replace('source<>', 'f.source<>')} "
            "ORDER BY f.id", [since, *params])
        return [r for r in rows if r.get("job_source") != "jury"]

    def dataset_zip(self, rows: Iterable[dict], out) -> dict:
        names = {u["login"]: u["name"] for u in self.db.all("SELECT login, name FROM users")}
        labels: list[dict] = []
        n_frames = 0
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for r in rows:
                frames = self._frames_for(r)
                paths = []
                for k, (ts, data) in enumerate(frames):
                    p = f"frames/{r['id']}/{k:02d}_{ts:.1f}s.jpg"
                    z.writestr(p, data)
                    paths.append(p)
                n_frames += len(paths)
                label = final_label(r)
                labels.append({
                    "finding_id": r["id"], "source": r["source"], "created_at": r["created_at"],
                    "camera_id": r.get("camera_id"), "camera_name": r.get("camera_name"),
                    "job_id": r.get("job_id"), "filename": r.get("filename"), "t_sec": r.get("t_sec"),
                    "type_code": r.get("type_code"), "type_name": r.get("type_name"),
                    "ai_confidence": r.get("confidence"), "ai_label": 1,
                    "operator_decision": r.get("decision"), "operator": names.get(r.get("decided_by") or "", r.get("decided_by")),
                    "operator_comment": r.get("decision_comment"),
                    "supervisor_result": r.get("verify_result"), "supervisor_comment": r.get("verify_comment"),
                    "label": int(bool(label)), "label_source": "supervisor" if r.get("verified") else "operator",
                    "description_ai": r.get("description_ai"), "description_operator": r.get("description_edit"),
                    "frames": paths,
                })
            z.writestr("labels.jsonl", "\n".join(json.dumps(x, ensure_ascii=False) for x in labels) + "\n")
            buf = io.StringIO()
            cols = [c for c in labels[0].keys() if c != "frames"] + ["frames"] if labels else ["finding_id"]
            w = csv.DictWriter(buf, fieldnames=cols)
            w.writeheader()
            for x in labels:
                w.writerow({**x, "frames": ";".join(x["frames"])})
            z.writestr("labels.csv", buf.getvalue())
            z.writestr("README.txt", DATASET_README.format(n=len(labels), frames=n_frames,
                                                              positives=sum(x["label"] for x in labels),
                                                              negatives=sum(1 - x["label"] for x in labels),
                                                              exported=datetime.now().isoformat(timespec="seconds")))
        return {"examples": len(labels), "frames": n_frames}

    def _frames_for(self, r: dict) -> list[tuple[float, bytes]]:
        if r["source"] == "upload":
            try:
                res = json.loads(Path(r["result_path"]).read_text(encoding="utf-8")) if r.get("result_path") else {}
            except Exception:
                return []
            viols = res.get("violations") or []
            i = r.get("violation_index")
            if i is None or not (0 <= i < len(viols)):
                return []
            out = []
            for fr in viols[i].get("evidence_frames") or []:
                try:
                    out.append((float(fr.get("timestamp_sec") or 0), base64.b64decode(fr["image_base64"])))
                except Exception:
                    continue
            return out
        fdir = Path(r.get("frames_dir") or "")
        meta = loads((fdir / "frames.json").read_text(encoding="utf-8"), {}) if (fdir / "frames.json").exists() else {}
        index = meta.get("frames") or []
        t0 = meta.get("t0") or 0.0
        at = meta.get("alert_ts") or t0
        out = []
        for x in index:
            if abs(x["ts"] - at) > 3.0:
                continue
            p = fdir / f"{x['n']:05d}.jpg"
            if p.exists():
                out.append((round(x["ts"] - t0, 2), p.read_bytes()))
        return out


DATASET_README = """PhantomGuard training dataset - exported {exported}

{n} labelled examples ({positives} violations, {negatives} not violations), {frames} frames.
Every example is a moment the AI flagged as a possible violation; the label is what people decided:
  label = 1  violation (operator confirmed and the supervisor agreed, or the supervisor overruled a rejection)
  label = 0  not a violation (operator rejected and the supervisor agreed, or the supervisor overruled a confirmation)
  label_source = supervisor when the decision was verified, operator otherwise.

labels.jsonl / labels.csv - one row per example: type_code (T01…T15), ai_confidence, operator decision and wording,
supervisor result, description_ai / description_operator, and the frame paths.
frames/<finding_id>/ - JPEG frames around the moment (uploads: the evidence frames; cameras: ±3 s around the alert).

Jury test videos are never included (brief, section 7). All data stays inside the bank: this archive was produced
on the PhantomGuard server from the bank's own recordings.
"""
