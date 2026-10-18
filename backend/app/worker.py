from __future__ import annotations

import heapq
import logging
import logging.handlers
import multiprocessing as mp
import os
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .analyzers import CallbackProgress, resolve

log = logging.getLogger("backend.worker")

PRIORITY_JURY, PRIORITY_UI, PRIORITY_REPLAY = 0, 1, 2


@dataclass
class Outcome:
    job_id: str
    kind: str
    result: dict | None = None
    error: str | None = None
    partial: dict | None = None
    duration_sec: float = 0.0
    attempts: int = 1
    worker: str = ""


@dataclass(order=True)
class _Pending:
    priority: int
    seq: int
    job_id: str = field(compare=False)
    path: str = field(compare=False)
    deadline: float = field(compare=False)
    attempts: int = field(compare=False, default=0)


@dataclass
class _Running:
    job_id: str
    path: str
    deadline: float
    budget_deadline: float
    kill_at: float
    started_at: float
    last_msg_at: float
    attempts: int
    token: int
    partial: dict | None = None
    stage: str = "started"
    progress: float = 0.0


def _worker_main(idx: int, analyzer_name: str, warmup: bool, in_q: Any, out_q: Any, log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        p = Path(log_file)
        try:
            handlers.append(logging.handlers.RotatingFileHandler(p.with_name(f"{p.stem}-worker{idx}{p.suffix}"),
                                                                 maxBytes=20 * 1024 * 1024, backupCount=2, encoding="utf-8"))
        except OSError:
            pass
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format=f"%(asctime)s %(levelname)s worker-{idx} %(name)s: %(message)s", handlers=handlers)
    wlog = logging.getLogger("backend.worker.proc")
    try:
        analyze, warm, version = resolve(analyzer_name)
    except Exception as e:
        out_q.put({"type": "fatal", "error": f"cannot load analyzer {analyzer_name!r}: {e}",
                   "trace": traceback.format_exc()})
        return
    info: Any = None
    if warm is not None and warmup:
        try:
            info = warm()
        except Exception as e:
            info = f"failed: {e}"
            wlog.exception("warmup failed")
    out_q.put({"type": "ready", "version": version, "warmup": info, "pid": os.getpid()})
    while True:
        cmd = in_q.get()
        if cmd is None or cmd.get("cmd") == "stop":
            break
        job_id = cmd["job_id"]
        progress = CallbackProgress(
            lambda st, p, _j=job_id: out_q.put({"type": "progress", "job_id": _j, "stage": st, "progress": p}),
            lambda r, _j=job_id: out_q.put({"type": "partial", "job_id": _j, "result": r}),
        )
        t0 = time.time()
        try:
            result = analyze(cmd["path"], on_progress=progress, deadline=cmd["deadline"])
            if not isinstance(result, dict):
                raise TypeError(f"analyzer returned {type(result).__name__}, expected dict")
            out_q.put({"type": "done", "job_id": job_id, "result": result, "sec": time.time() - t0})
        except Exception as e:
            wlog.error("job %s failed: %s", job_id, e, exc_info=True)
            out_q.put({"type": "failed", "job_id": job_id, "error": f"{type(e).__name__}: {e}"[:500],
                       "trace": traceback.format_exc()[-4000:], "sec": time.time() - t0})
    out_q.put({"type": "bye"})


class _Worker:
    def __init__(self, pool: "WorkerPool", idx: int):
        self.pool = pool
        self.idx = idx
        self.name = f"w{idx}"
        self.state = "starting"
        self.version: str = ""
        self.warmup_info: Any = None
        self.current: _Running | None = None
        self.generation = 0
        self.started_at = time.time()
        self.jobs_done = 0
        self.failures = 0
        self.respawn_at = 0.0
        self._proc: mp.Process | None = None
        self._in_q: Any = None
        self._out_q: Any = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._thread_analyzer: tuple[Callable, Callable | None, str] | None = None

    def start(self) -> None:
        self.generation += 1
        self._stop = threading.Event()
        self.state = "starting"
        self.started_at = time.time()
        if self.pool.mode == "process":
            ctx = mp.get_context("spawn")
            self._in_q, self._out_q = ctx.Queue(), ctx.Queue()
            self._proc = ctx.Process(target=_worker_main, name=f"analyzer-{self.idx}", daemon=True,
                                     args=(self.idx, self.pool.analyzer_name, self.pool.warmup,
                                           self._in_q, self._out_q, self.pool.log_file))
            self._proc.start()
            self._reader = threading.Thread(target=self._read_loop, name=f"reader-{self.idx}", daemon=True)
            self._reader.start()
        else:
            threading.Thread(target=self._thread_warmup, name=f"warmup-{self.idx}", daemon=True).start()

    def alive(self) -> bool:
        if self.pool.mode == "process":
            return self._proc is not None and self._proc.is_alive()
        return self.state != "dead"

    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    def kill(self) -> None:
        self._stop.set()
        self.state = "dead"
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.join(5)
            except Exception:
                log.exception("worker %s: kill failed", self.name)
            for q_ in (self._in_q, self._out_q):
                try:
                    q_.close()
                    q_.join_thread()
                except Exception:
                    pass
            self._in_q = self._out_q = None
        self._proc = None

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None and self._proc.is_alive():
            try:
                self._in_q.put({"cmd": "stop"})
                self._proc.join(3)
            except Exception:
                pass
            if self._proc.is_alive():
                self._proc.kill()
                self._proc.join(2)
        for q_ in (self._in_q, self._out_q):
            try:
                q_.close()
                q_.join_thread()
            except Exception:
                pass
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(2)
        self._in_q = self._out_q = None
        self.state = "dead"

    def run(self, job: _Pending, budget_deadline: float | None = None) -> None:
        now = time.time()
        budget = min(job.deadline, budget_deadline) if budget_deadline else job.deadline
        self.current = _Running(job_id=job.job_id, path=job.path, deadline=job.deadline, budget_deadline=budget,
                                kill_at=job.deadline + self.pool.grace_sec, started_at=now, last_msg_at=now,
                                attempts=job.attempts + 1, token=self.generation * 1_000_000 + int(now * 1000) % 1_000_000)
        self.state = "busy"
        if self.pool.mode == "process":
            self._in_q.put({"cmd": "run", "job_id": job.job_id, "path": job.path, "deadline": budget})
        else:
            threading.Thread(target=self._thread_run, args=(self.current,), name=f"job-{job.job_id}", daemon=True).start()

    def _read_loop(self) -> None:
        gen = self.generation
        while not self._stop.is_set():
            try:
                msg = self._out_q.get(timeout=0.5)
            except queue.Empty:
                continue
            except (EOFError, OSError, ValueError):
                break
            if gen != self.generation:
                break
            self.pool._on_message(self, msg)

    def _thread_warmup(self) -> None:
        try:
            analyze, warm, version = resolve(self.pool.analyzer_name)
            info = None
            if warm is not None and self.pool.warmup:
                try:
                    info = warm()
                except Exception as e:
                    info = f"failed: {e}"
            self._thread_analyzer = (analyze, warm, version)
            self.pool._on_message(self, {"type": "ready", "version": version, "warmup": info, "pid": os.getpid()})
        except Exception as e:
            self.pool._on_message(self, {"type": "fatal", "error": str(e), "trace": traceback.format_exc()})

    def _thread_run(self, running: _Running) -> None:
        analyze = self._thread_analyzer[0]  # type: ignore[index]
        job_id, token = running.job_id, running.token

        def send(msg: dict) -> None:
            if self.current is not None and self.current.token == token:
                self.pool._on_message(self, msg)

        progress = CallbackProgress(
            lambda st, p: send({"type": "progress", "job_id": job_id, "stage": st, "progress": p}),
            lambda r: send({"type": "partial", "job_id": job_id, "result": r}),
        )
        t0 = time.time()
        try:
            result = analyze(running.path, on_progress=progress, deadline=running.budget_deadline)
            if not isinstance(result, dict):
                raise TypeError(f"analyzer returned {type(result).__name__}, expected dict")
            send({"type": "done", "job_id": job_id, "result": result, "sec": time.time() - t0})
        except Exception as e:
            log.error("job %s failed: %s", job_id, e, exc_info=True)
            send({"type": "failed", "job_id": job_id, "error": f"{type(e).__name__}: {e}"[:500],
                  "trace": traceback.format_exc()[-4000:], "sec": time.time() - t0})


class WorkerPool:
    def __init__(self, analyzer_name: str, mode: str = "process", workers: int = 1, warmup: bool = True,
                 grace_sec: float = 8.0, stall_sec: float = 150.0, max_attempts: int = 2,
                 retry_on_error: bool = True, min_budget_sec: float = 35.0,
                 on_finish: Callable[[Outcome], None] | None = None,
                 on_progress: Callable[[str, str, float], None] | None = None,
                 log_file: str | None = None):
        if mode not in ("process", "thread"):
            raise ValueError("WORKER_MODE must be process or thread")
        self.analyzer_name = analyzer_name
        self.mode = mode
        self.warmup = warmup
        self.grace_sec = grace_sec
        self.stall_sec = stall_sec
        self.max_attempts = max(1, max_attempts)
        self.retry_on_error = retry_on_error
        self.min_budget_sec = min_budget_sec
        self.max_start_failures = 5
        self.log_file = log_file
        self.on_finish = on_finish or (lambda o: None)
        self.on_progress = on_progress or (lambda j, s, p: None)
        self._lock = threading.RLock()
        self._pending: list[_Pending] = []
        self._pending_ids: set[str] = set()
        self._seq = 0
        self._workers = [_Worker(self, i) for i in range(max(1, workers))]
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._sched = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self.fatal: str | None = None

    def start(self) -> None:
        for w in self._workers:
            w.start()
        self._sched.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for w in self._workers:
            w.stop()
        if self._sched.is_alive() and self._sched is not threading.current_thread():
            self._sched.join(3)

    def submit(self, job_id: str, path: str, priority: int, deadline: float, attempts: int = 0) -> None:
        with self._lock:
            if job_id in self._pending_ids or any(w.current and w.current.job_id == job_id for w in self._workers):
                return
            self._seq += 1
            heapq.heappush(self._pending, _Pending(priority, self._seq, job_id, path, deadline, attempts))
            self._pending_ids.add(job_id)
        self._wake.set()

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in self._pending_ids:
                return False
            self._pending = [p for p in self._pending if p.job_id != job_id]
            heapq.heapify(self._pending)
            self._pending_ids.discard(job_id)
            return True

    def abort(self, job_id: str) -> bool:
        if self.cancel(job_id):
            return True
        with self._lock:
            for w in self._workers:
                if w.current is not None and w.current.job_id == job_id:
                    log.warning("job %s aborted on %s", job_id, w.name)
                    w.current = None
                    self._replace(w)
                    self._wake.set()
                    return True
        return False

    def queue_size(self) -> int:
        with self._lock:
            return len(self._pending)

    def position(self, job_id: str) -> int | None:
        with self._lock:
            order = sorted(self._pending)
            for i, p in enumerate(order):
                if p.job_id == job_id:
                    return i
        return None

    def running_ids(self) -> list[str]:
        with self._lock:
            return [w.current.job_id for w in self._workers if w.current]

    def busy(self) -> bool:
        with self._lock:
            return bool(self._pending) or any(w.current for w in self._workers)

    def ready(self) -> bool:
        with self._lock:
            return any(w.state in ("idle", "busy") for w in self._workers)

    def stats(self) -> dict:
        with self._lock:
            return {
                "mode": self.mode,
                "queued": len(self._pending),
                "running": [w.current.job_id for w in self._workers if w.current],
                "fatal": self.fatal,
                "workers": [{
                    "name": w.name, "state": w.state, "pid": w.pid(), "version": w.version,
                    "warmup": w.warmup_info, "jobs_done": w.jobs_done,
                    "current": w.current.job_id if w.current else None,
                    "uptime_sec": round(time.time() - w.started_at, 1),
                } for w in self._workers],
            }

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.25)
            self._wake.clear()
            try:
                self._tick()
            except Exception:
                log.exception("scheduler tick failed")

    def _tick(self) -> None:
        now = time.time()
        with self._lock:
            for w in self._workers:
                if w.state != "dead" and self.mode == "process" and not w.alive():
                    was_starting = w.state == "starting"
                    log.error("worker %s died unexpectedly (pid=%s, state=%s)", w.name, w.pid(), w.state)
                    self._handle_exit(w, "crash", "worker process died")
                    w.kill()
                    if was_starting:
                        w.failures += 1
                        if w.failures >= self.max_start_failures:
                            self.fatal = f"worker {w.name} failed to start {w.failures} times; check the analyzer / logs"
                            log.error(self.fatal)
                            continue
                        w.respawn_at = now + min(30.0, 2.0 ** w.failures)
                    continue
                if w.state == "dead" and not self._stop.is_set() and now >= w.respawn_at \
                        and w.failures < self.max_start_failures:
                    w.start()
                    continue
                r = w.current
                if r is None:
                    continue
                if now > r.kill_at:
                    log.warning("job %s exceeded hard deadline on %s -> killing", r.job_id, w.name)
                    self._handle_exit(w, "deadline", f"hard deadline {int(r.kill_at - r.started_at)} s exceeded")
                    self._replace(w)
                elif now - r.last_msg_at > self.stall_sec:
                    log.warning("job %s: no progress for %.0f s on %s -> killing", r.job_id, now - r.last_msg_at, w.name)
                    self._handle_exit(w, "stall", f"no progress for {int(self.stall_sec)} s")
                    self._replace(w)
            for w in self._workers:
                if w.state == "idle" and self._pending:
                    job = heapq.heappop(self._pending)
                    self._pending_ids.discard(job.job_id)
                    if job.deadline + self.grace_sec < now:
                        log.warning("job %s: deadline already passed while queued", job.job_id)
                        self._finish(Outcome(job.job_id, "deadline", error="deadline passed in queue",
                                             attempts=job.attempts + 1, worker=w.name))
                        continue
                    budget = self._budget_deadline(job, now)
                    log.info("job %s -> %s (priority %d, queued %d, budget %.0f s)", job.job_id, w.name, job.priority,
                             len(self._pending), budget - now)
                    w.run(job, budget)
                    self.on_progress(job.job_id, "started", 0.0)

    def _budget_deadline(self, job: _Pending, now: float) -> float:
        behind = [p for p in self._pending if p.priority <= job.priority]
        if not behind:
            return job.deadline
        earliest = min(p.deadline for p in behind + [job])
        share = (earliest - now) / (len(behind) + 1) / max(1, len(self._workers))
        return min(job.deadline, now + max(self.min_budget_sec, share))

    def _replace(self, w: _Worker) -> None:
        if self.mode == "process":
            w.kill()
            w.start()
        else:
            w.current = None
            w.state = "idle"

    def _handle_exit(self, w: _Worker, kind: str, error: str) -> None:
        r = w.current
        w.current = None
        if r is None:
            return
        now = time.time()
        retry = kind == "crash" and r.attempts < self.max_attempts and (r.deadline - now) > 45
        if retry:
            log.warning("job %s: retrying after crash (attempt %d)", r.job_id, r.attempts + 1)
            self.on_progress(r.job_id, "retry", 0.0)
            self._seq += 1
            heapq.heappush(self._pending, _Pending(-1, self._seq, r.job_id, r.path, r.deadline, r.attempts))
            self._pending_ids.add(r.job_id)
            return
        self._finish(Outcome(r.job_id, kind, error=error, partial=r.partial,
                             duration_sec=now - r.started_at, attempts=r.attempts, worker=w.name))

    def _finish(self, outcome: Outcome) -> None:
        try:
            self.on_finish(outcome)
        except Exception:
            log.exception("on_finish failed for job %s", outcome.job_id)

    def _on_message(self, w: _Worker, msg: dict) -> None:
        t = msg.get("type")
        with self._lock:
            if t == "ready":
                w.state = "idle"
                w.failures = 0
                w.version = msg.get("version", "")
                w.warmup_info = msg.get("warmup")
                log.info("worker %s ready (pid=%s, %s) warmup=%s", w.name, msg.get("pid"), w.version, w.warmup_info)
                self._wake.set()
                return
            if t == "fatal":
                self.fatal = msg.get("error")
                w.state = "dead"
                log.error("worker %s fatal: %s\n%s", w.name, msg.get("error"), msg.get("trace", ""))
                return
            if t in ("log", "bye"):
                return
            r = w.current
            if r is None or r.job_id != msg.get("job_id"):
                return
            r.last_msg_at = time.time()
            if t == "progress":
                r.stage, r.progress = msg.get("stage", r.stage), float(msg.get("progress", r.progress))
                self.on_progress(r.job_id, r.stage, r.progress)
                return
            if t == "partial":
                r.partial = msg.get("result")
                return
            if t == "failed" and self.retry_on_error and r.attempts < self.max_attempts \
                    and (r.deadline - time.time()) > 45:
                log.warning("job %s: analyzer error, retrying (attempt %d): %s", r.job_id, r.attempts + 1, msg.get("error"))
                w.current = None
                w.state = "idle"
                self.on_progress(r.job_id, "retry", 0.0)
                self._seq += 1
                heapq.heappush(self._pending, _Pending(-1, self._seq, r.job_id, r.path, r.deadline, r.attempts))
                self._pending_ids.add(r.job_id)
                self._wake.set()
                return
            if t in ("done", "failed"):
                w.current = None
                w.state = "idle"
                w.jobs_done += 1
                outcome = Outcome(r.job_id, t, result=msg.get("result"), error=msg.get("error"), partial=r.partial,
                                  duration_sec=float(msg.get("sec", 0.0)), attempts=r.attempts, worker=w.name)
                self._wake.set()
        if t in ("done", "failed"):
            self._finish(outcome)
