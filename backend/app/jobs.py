"""Очередь задач: одна видеокарта -> один воркер, задачи по очереди. Состояние пишется на диск."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Callable

from . import config

log = logging.getLogger("backend.jobs")

PUBLIC_ORDER = ("job_id", "status", "verdict", "violations")


class JobStore:
    def __init__(self, jobs_dir: Path):
        self.dir = jobs_dir
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        for p in self.dir.glob("*.json"):
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
                self.jobs[j["job_id"]] = j
            except Exception:  # битый файл не должен ронять сервис
                log.exception("не прочитан %s", p)

    def new(self, filename: str, upload_path: Path) -> dict:
        job = {
            "job_id": uuid.uuid4().hex[:12],
            "status": "processing",
            "stage": "queued",
            "progress": 0.0,
            "created_at": time.time(),
            "filename": filename,
            "upload_path": str(upload_path),
        }
        self.save(job)
        return job

    def save(self, job: dict) -> None:
        with self.lock:
            self.jobs[job["job_id"]] = job
            tmp = self.dir / f"{job['job_id']}.json.tmp"
            tmp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.dir / f"{job['job_id']}.json")

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            return self.jobs.get(job_id)

    def update(self, job_id: str, **fields) -> None:
        job = self.get(job_id)
        if job is None:
            return
        job.update(fields)
        self.save(job)


def public_view(job: dict, include_extras: bool = True) -> dict:
    """Ответ GET /jobs/{id}: обязательные поля ТЗ первыми, затем доп. поля для интерфейса."""
    out: dict = {"job_id": job["job_id"], "status": job["status"]}
    res = job.get("result") or {}
    if job["status"] == "done":
        out["verdict"] = res.get("verdict")
        out["violations"] = res.get("violations", [])
    if include_extras:
        out["stage"] = job.get("stage")
        out["progress"] = round(job.get("progress", 0.0), 2)
        if job["status"] == "done":
            out["timeline"] = res.get("timeline")
            out["meta"] = res.get("meta")
        if job.get("error"):
            out["error"] = job["error"]
        if job.get("finished_at"):
            out["processing_sec"] = round(job["finished_at"] - job["created_at"], 1)
    return out


class Worker:
    def __init__(self, store: JobStore, analyze: Callable):
        self.store = store
        self.analyze = analyze
        self.q: queue.Queue[str] = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="analyzer", daemon=True)
        self.cleaner = threading.Thread(target=self._clean, name="cleaner", daemon=True)

    def start(self) -> None:
        # задачи, прерванные перезапуском, ставим обратно (если видео ещё на диске)
        for job in list(self.store.jobs.values()):
            if job["status"] == "processing":
                if Path(job.get("upload_path", "")).exists():
                    self.q.put(job["job_id"])
                else:
                    self.store.update(job["job_id"], status="failed", error="сервис перезапущен, видео не найдено")
        self.thread.start()
        self.cleaner.start()

    def submit(self, job_id: str) -> None:
        self.q.put(job_id)

    def queue_size(self) -> int:
        return self.q.qsize()

    def _run(self) -> None:
        while True:
            job_id = self.q.get()
            job = self.store.get(job_id)
            if job is None:
                continue
            started = time.time()
            self.store.update(job_id, stage="started", started_at=started)

            def progress(stage: str, p: float, _id=job_id) -> None:
                self.store.update(_id, stage=stage, progress=float(p))

            deadline = job["created_at"] + config.JOB_HARD_LIMIT_SEC
            try:
                result = self.analyze(job["upload_path"], on_progress=progress, deadline=deadline)
                self.store.update(job_id, status="done", stage="done", progress=1.0,
                                  result=result, finished_at=time.time())
                log.info("job %s done in %.1fs: %s", job_id, time.time() - started, result.get("verdict"))
            except Exception as e:
                log.error("job %s failed: %s\n%s", job_id, e, traceback.format_exc())
                self.store.update(job_id, status="failed", stage="failed", error=str(e)[:500],
                                  finished_at=time.time())

    def _clean(self) -> None:
        while True:
            time.sleep(60)
            now = time.time()
            for job in list(self.store.jobs.values()):
                p = Path(job.get("upload_path", ""))
                if job["status"] != "processing" and p.exists() and now - job.get("finished_at", now) > config.VIDEO_TTL_SEC:
                    try:
                        p.unlink()
                        log.info("удалено видео задачи %s (TTL)", job["job_id"])
                    except OSError:
                        pass
