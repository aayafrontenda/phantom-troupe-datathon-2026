from __future__ import annotations

import time

import pytest

from backend.tests.conftest import make_app, upload, wait_done, wait_ready

FAKE = "backend.tests.fake_analyzers"


@pytest.mark.parametrize("mode", ["thread", "process"])
def test_jury_jobs_go_first(tmp_path, video, video2, mode):
    with make_app(tmp_path, ANALYZER=f"{FAKE}:slow", FAKE_SLOW_SEC="0.8", WORKER_MODE=mode, DEDUP="0") as (c, st):
        wait_ready(c)
        first = upload(c, video).json()["job_id"]
        ui_job = upload(c, video2, key=None, ui=True).json()["job_id"]
        ui_job2 = upload(c, video, key=None, ui=True).json()["job_id"]
        jury_job = upload(c, video2).json()["job_id"]
        assert st.pool.position(jury_job) == 0
        assert st.pool.position(ui_job) == 1
        j = c.get(f"/ui/api/jobs/{ui_job2}").json()
        assert j["status"] == "processing" and j["queue_position"] == 2 and j["eta_sec"] >= 1
        order = []
        for jid in (first, jury_job, ui_job, ui_job2):
            row = wait_done(c, jid)
            assert row["status"] == "done"
            order.append((st.jobs.get(jid)["started_at"], jid))
        order.sort()
        assert [j for _, j in order] == [first, jury_job, ui_job, ui_job2]


@pytest.mark.parametrize("mode", ["thread", "process"])
def test_deadline_returns_partial_result(tmp_path, video, mode):
    with make_app(tmp_path, ANALYZER=f"{FAKE}:slow_with_partial", WORKER_MODE=mode,
                  JOB_HARD_LIMIT_SEC="2", WATCHDOG_GRACE_SEC="0.5") as (c, st):
        wait_ready(c)
        t0 = time.time()
        job_id = upload(c, video).json()["job_id"]
        j = wait_done(c, job_id, timeout=20)
        assert time.time() - t0 < 8
        assert j["status"] == "done" and j["verdict"] == "violation"
        assert j["violations"][0]["type"] == "Частичное"
        assert j["partial"] is True and "deadline" in j["warning"]
        from ml.schema import validate_job
        assert validate_job(j) == []
        wait_ready(c)
        assert st.pool.stats()["running"] == []


def test_stall_watchdog_kills_hung_pipeline(tmp_path, video):
    with make_app(tmp_path, ANALYZER=f"{FAKE}:hang", WORKER_MODE="process",
                  JOB_HARD_LIMIT_SEC="60", WORKER_STALL_SEC="1.5", WATCHDOG_GRACE_SEC="0.5") as (c, st):
        wait_ready(c)
        job_id = upload(c, video).json()["job_id"]
        j = wait_done(c, job_id, timeout=20)
        assert j["status"] == "done" and j["verdict"] == "no_violation" and j["partial"] is True
        assert "stall" in j["warning"]


def test_deadline_failed_policy(tmp_path, video):
    with make_app(tmp_path, ANALYZER=f"{FAKE}:hang", WORKER_MODE="thread", ON_DEADLINE="failed",
                  JOB_HARD_LIMIT_SEC="1", WATCHDOG_GRACE_SEC="0.3") as (c, st):
        wait_ready(c)
        j = wait_done(c, upload(c, video).json()["job_id"], timeout=20)
        assert j["status"] == "failed" and "deadline" in j["error"]


def test_crash_is_isolated_and_retried(tmp_path, video):
    with make_app(tmp_path, ANALYZER=f"{FAKE}:crash_once", WORKER_MODE="process", WARMUP="0") as (c, st):
        wait_ready(c)
        pid_before = st.pool.stats()["workers"][0]["pid"]
        j = wait_done(c, upload(c, video).json()["job_id"], timeout=40)
        assert j["status"] == "done" and j["verdict"] == "violation"
        assert j["meta"]["attempts"] == 2
        wait_ready(c)
        assert st.pool.stats()["workers"][0]["pid"] != pid_before
        assert c.get("/health").json()["status"] == "ok"


def test_permanent_crash_ends_as_partial_not_lost(tmp_path, video):
    with make_app(tmp_path, ANALYZER=f"{FAKE}:crash", WORKER_MODE="process", MAX_ATTEMPTS="2") as (c, st):
        wait_ready(c)
        j = wait_done(c, upload(c, video).json()["job_id"], timeout=60)
        assert j["status"] == "done" and j["verdict"] == "no_violation" and j["partial"] is True
        assert "crash" in j["warning"]


def test_analyzer_exception_policy(tmp_path, video):
    with make_app(tmp_path, ANALYZER=f"{FAKE}:raise_error", WORKER_MODE="thread", ON_FAILURE="failed",
                  RETRY_ON_ERROR="0") as (c, st):
        wait_ready(c)
        j = wait_done(c, upload(c, video).json()["job_id"])
        assert j["status"] == "failed" and "boom" in j["error"]
    with make_app(tmp_path / "b", ANALYZER=f"{FAKE}:raise_error", WORKER_MODE="thread", ON_FAILURE="partial",
                  RETRY_ON_ERROR="1") as (c, st):
        wait_ready(c)
        j = wait_done(c, upload(c, video).json()["job_id"])
        assert j["status"] == "done" and j["verdict"] == "no_violation" and j["partial"] is True
        assert st.jobs.get(j["job_id"])["attempts"] == 2


def test_bad_result_is_repaired(tmp_path, video):
    from ml.schema import validate_job
    with make_app(tmp_path, ANALYZER=f"{FAKE}:bad_result", WORKER_MODE="thread") as (c, st):
        wait_ready(c)
        j = wait_done(c, upload(c, video).json()["job_id"])
        assert j["status"] == "done"
        assert validate_job(j) == []
        assert j["verdict"] == "violation"
        assert len(j["violations"]) == 2
        assert j["violations"][0]["timecode_sec"] == 1.2
        assert 1 <= len(j["violations"][0]["evidence_frames"]) <= 3
        assert j["violations"][0]["type"]
        assert "schema fixes" in j["warning"]


def test_restart_recovers_queued_jobs(tmp_path, video, video2):
    with make_app(tmp_path, ANALYZER=f"{FAKE}:slow", FAKE_SLOW_SEC="30", WORKER_MODE="thread", DEDUP="0") as (c, st):
        wait_ready(c)
        running = upload(c, video).json()["job_id"]
        queued = upload(c, video2).json()["job_id"]
        time.sleep(0.5)
        assert st.jobs.get(running)["status"] == "running"
        assert st.jobs.get(queued)["status"] == "queued"
    with make_app(tmp_path, ANALYZER=f"{FAKE}:quick", WORKER_MODE="thread", DEDUP="0") as (c, st):
        wait_ready(c)
        for jid in (running, queued):
            j = wait_done(c, jid, timeout=30)
            assert j["status"] == "done", j
    with make_app(tmp_path, ANALYZER=f"{FAKE}:slow", FAKE_SLOW_SEC="30", WORKER_MODE="thread", DEDUP="0") as (c, st):
        wait_ready(c)
        gone = upload(c, video).json()["job_id"]
        time.sleep(0.3)
        import pathlib
        pathlib.Path(st.jobs.get(gone)["upload_path"]).unlink()
    with make_app(tmp_path, ANALYZER=f"{FAKE}:quick", WORKER_MODE="thread") as (c, st):
        j = c.get(f"/api/v1/jobs/{gone}", headers={"X-API-Key": "test-key"}).json()
        assert j["status"] == "failed" and "restarted" in j["error"]


def test_requeue_with_replay_priority(tmp_path, video):
    with make_app(tmp_path, ANALYZER=f"{FAKE}:quick", WORKER_MODE="thread") as (c, st):
        wait_ready(c)
        jid = upload(c, video).json()["job_id"]
        wait_done(c, jid)
        r = c.post(f"/admin/api/jobs/{jid}/requeue", headers={"X-API-Key": "admin-key"})
        assert r.status_code == 200
        j = wait_done(c, jid)
        assert j["status"] == "done" and st.jobs.get(jid)["attempts"] >= 1


def test_budget_is_shared_with_queued_jobs():
    from backend.app.worker import WorkerPool, _Pending

    pool = WorkerPool("mock", mode="thread", workers=1, warmup=False, min_budget_sec=35)
    now = 1000.0
    head = _Pending(0, 1, "a", "a.mov", deadline=now + 270)
    assert pool._budget_deadline(head, now) == now + 270
    for i in range(4):
        pool.submit(f"j{i}", f"{i}.mov", 0, now + 270 + i)
    assert pool._budget_deadline(head, now) == pytest.approx(now + 270 / 5)
    pool.submit("ui", "ui.mov", 1, now + 270)
    assert pool._budget_deadline(head, now) == pytest.approx(now + 270 / 5)
    late = _Pending(0, 9, "z", "z.mov", deadline=now + 40)
    assert pool._budget_deadline(late, now) == now + 35
    tight = _Pending(0, 9, "z", "z.mov", deadline=now + 20)
    assert pool._budget_deadline(tight, now) == now + 20
