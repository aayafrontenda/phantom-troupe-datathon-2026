"""Application state: one object that owns every long-lived service (built once in main.create_app)."""
from __future__ import annotations

import base64
import logging
import threading
import time
from dataclasses import dataclass, field

from . import metrics
from .alerts import AlertEngine
from .auth import KeyStore, RateLimiter
from .config import Settings
from .db import Database
from .events import EventBus
from .findings import FindingService
from .jobs import JobService
from .quality import QualityService
from .live import CameraManager
from .reports import make_clips
from .storage import Retention
from .users import UserStore
from .worker import WorkerPool

log = logging.getLogger("backend.state")


@dataclass
class AppState:
    settings: Settings
    db: Database
    keys: KeyStore
    users: UserStore
    bus: EventBus
    pool: WorkerPool
    jobs: JobService
    alerts: AlertEngine
    findings: FindingService
    quality: QualityService
    cameras: CameraManager
    retention: Retention
    limiter: RateLimiter
    started_at: float = field(default_factory=time.time)
    log_file: str | None = None
    _stop: threading.Event = field(default_factory=threading.Event)

    @classmethod
    def build(cls, settings: Settings, log_file: str | None = None) -> "AppState":
        db = Database(settings.db_path)
        bus = EventBus()
        keys = KeyStore(db)
        users = UserStore(db)
        alerts = AlertEngine(db, bus, settings)
        quality = QualityService(db, settings)
        findings = FindingService(db, bus, alerts, quality=quality)
        pool = WorkerPool(settings.analyzer, mode=settings.worker_mode, workers=settings.workers,
                          warmup=settings.warmup, grace_sec=settings.watchdog_grace_sec,
                          stall_sec=settings.worker_stall_sec, max_attempts=settings.max_attempts,
                          retry_on_error=settings.retry_on_error, log_file=log_file)
        state = cls(settings=settings, db=db, keys=keys, users=users, bus=bus, pool=pool, jobs=None, alerts=alerts,  # type: ignore[arg-type]
                    findings=findings, quality=quality, cameras=None, retention=Retention(db), limiter=RateLimiter(settings.rate_limit_per_min),  # type: ignore[arg-type]
                    log_file=log_file)
        state.jobs = JobService(db, pool, bus, on_result=state._on_result, findings=findings)
        pool.on_finish = state._on_finish
        pool.on_progress = state.jobs.on_progress
        state.cameras = CameraManager(db, bus, on_alert=state._on_live_alert, busy=pool.busy, on_clip=findings.from_camera)
        return state

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.pool.start()
        self.jobs.recover()
        self.retention.start()
        self.alerts.start()
        self.cameras.start_all()
        threading.Thread(target=self._gauges, name="gauges", daemon=True).start()
        log.info("service started: analyzer=%s workers=%d mode=%s storage=%s version=%s",
                 self.settings.analyzer, self.settings.workers, self.settings.worker_mode,
                 self.settings.storage_dir, self.settings.version)
        log.info("jury API key: %s… (full key: API_KEY env or storage/api_key.txt)", self.keys.jury_key[:6])

    def stop(self) -> None:
        self._stop.set()
        self.cameras.stop_all()
        self.alerts.stop()
        self.retention.stop()
        self.pool.stop()
        self.db.close()

    def _gauges(self) -> None:
        while not self._stop.wait(2):
            try:
                st = self.pool.stats()
                metrics.QUEUE_DEPTH.set(st["queued"])
                metrics.WORKERS_BUSY.set(len(st["running"]))
                metrics.WORKERS_READY.set(sum(1 for w in st["workers"] if w["state"] in ("idle", "busy")))
            except Exception:
                pass

    # ------------------------------------------------------------------ hooks
    def _on_finish(self, outcome) -> None:
        job = self.jobs.get(outcome.job_id) or {}
        self.jobs.on_finish(outcome)
        done = self.jobs.get(outcome.job_id) or {}
        metrics.JOBS_TOTAL.labels(done.get("status", "unknown"), job.get("source", "unknown")).inc()
        if outcome.kind != "done":
            metrics.JOB_PARTIAL_TOTAL.labels(outcome.kind).inc()
        if outcome.duration_sec:
            metrics.JOB_ANALYSIS_SECONDS.observe(outcome.duration_sec)
        if done.get("finished_at"):
            metrics.JOB_TOTAL_SECONDS.observe(done["finished_at"] - (done.get("request_started_at") or done["created_at"]))

    def _on_result(self, job: dict, result: dict) -> None:
        """After a job is stored: findings for the review workflow, clips in the background, alerts."""
        try:
            self.findings.from_job(job, result)
        except Exception:
            log.exception("job %s: findings failed", job["job_id"])
        threading.Thread(target=self._clips, args=(job, result), name=f"clips-{job['job_id']}", daemon=True).start()
        for v in result.get("violations") or []:
            frames = v.get("evidence_frames") or []
            self.alerts.handle(self._apply_threshold({
                "source": "job", "job_id": job["job_id"], "filename": job.get("filename"),
                "type_code": v.get("type_code") or "T99", "type_name": v.get("type"),
                "t_sec": v.get("timecode_sec"), "confidence": v.get("confidence"),
                "message": (v.get("description") or "")[:400],
                "norm": _norm_text(v), "evidence_b64": frames[0].get("image_base64") if frames else None,
                "link": f"/checks/{job['job_id']}",
            }), actor=job.get("source"))

    def _clips(self, job: dict, result: dict) -> None:
        try:
            clips = make_clips(job, result)
            if clips:
                self.bus.publish(f"job:{job['job_id']}", {"type": "clips", "job_id": job["job_id"], "count": len(clips)})
        except Exception:
            log.exception("job %s: clips failed", job["job_id"])

    def _on_live_alert(self, event: dict) -> dict | None:
        return self.alerts.handle(self._apply_threshold(event), actor="live")

    def _apply_threshold(self, event: dict) -> dict:
        """Adaptive per-type thresholds (learned from verified decisions): below it an alert is only ``low``."""
        try:
            if self.quality.below_threshold(event.get("type_code"), event.get("confidence")):
                event["below_threshold"] = True
                if event.get("severity") not in ("info",):
                    event["severity"] = "low"
        except Exception:
            log.exception("threshold check failed")
        return event


def _norm_text(v: dict) -> str | None:
    rule = v.get("rule") or {}
    refs = rule.get("refs") or []
    parts = [f"{r.get('point')} — {r.get('document')}" if r.get("point") else r.get("document", "") for r in refs]
    return "; ".join(p for p in parts if p) or None


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
