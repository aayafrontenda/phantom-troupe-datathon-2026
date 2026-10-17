"""Jury API contract, auth, upload validation, UI routes. Run from the repo root: pytest -q"""
from __future__ import annotations

import json

from backend.tests.conftest import upload, wait_done, wait_ready


def test_requires_key(app_factory, video):
    with app_factory() as (c, st):
        assert upload(c, video, key=None).status_code == 401
        assert upload(c, video, key="wrong").status_code == 401
        assert c.get("/api/v1/jobs/whatever", headers={"X-API-Key": "wrong"}).status_code == 401
        assert c.get("/api/v1/jobs/whatever", headers={"X-API-Key": "test-key"}).status_code == 404
        # bearer form is accepted too
        assert c.get("/api/v1/jobs/whatever", headers={"Authorization": "Bearer test-key"}).status_code == 404


def test_upload_validation(app_factory, video, tmp_path):
    with app_factory(MAX_UPLOAD_MB="1") as (c, st):
        h = {"X-API-Key": "test-key"}
        r = c.post("/api/v1/analyze", headers=h, files={"file": ("notes.txt", b"hello", "text/plain")})
        assert r.status_code == 400
        r = c.post("/api/v1/analyze", headers=h, files={"file": ("empty.mov", b"", "video/quicktime")})
        assert r.status_code == 400
        r = c.post("/api/v1/analyze", headers=h, files={"file": ("junk.mov", b"\x00" * 5000, "video/quicktime")})
        assert r.status_code == 400
        big = tmp_path / "big.mov"
        big.write_bytes(b"\x00" * (2 * 1024 * 1024))
        assert upload(c, big).status_code == 413
        r = c.post("/api/v1/analyze", headers=h, data={"x": "1"})
        assert r.status_code == 400
        assert "file" in r.json()["detail"]
        # nothing leaked into the upload dir
        assert not list(st.settings.upload_dir.glob("*"))


def test_full_flow_schema_and_order(app_factory, video):
    from ml.schema import validate_job
    with app_factory() as (c, st):
        wait_ready(c)
        r = upload(c, video)
        assert r.status_code == 200, r.text
        assert set(r.json()) >= {"job_id", "status"}
        job_id = r.json()["job_id"]
        j = wait_done(c, job_id)
        assert j["status"] == "done", j
        assert validate_job(j) == []
        assert list(j)[:4] == ["job_id", "status", "verdict", "violations"]
        assert j["processing_sec"] >= 0
        # result file on disk, upload still present (TTL not reached)
        row = st.jobs.get(job_id)
        assert row["result_path"] and row["upload_path"]
        assert json.loads(open(row["result_path"], encoding="utf-8").read())["verdict"] == j["verdict"]


def test_dedup_identical_file(app_factory, video):
    with app_factory() as (c, st):
        wait_ready(c)
        j1 = wait_done(c, upload(c, video).json()["job_id"])
        r2 = upload(c, video)
        j2 = c.get(f"/api/v1/jobs/{r2.json()['job_id']}", headers={"X-API-Key": "test-key"}).json()
        assert j2["status"] == "done"
        assert j2["dedup_of"] == j1["job_id"]
        assert j2["verdict"] == j1["verdict"]
        assert len(j2["violations"]) == len(j1["violations"])
    # dedup can be disabled
    with app_factory(DEDUP="0") as (c, st):
        wait_ready(c)
        wait_done(c, upload(c, video).json()["job_id"])
        r2 = upload(c, video)
        j2 = c.get(f"/api/v1/jobs/{r2.json()['job_id']}", headers={"X-API-Key": "test-key"}).json()
        assert "dedup_of" not in j2


def test_ui_routes(app_factory, video):
    with app_factory() as (c, st):
        wait_ready(c)
        r = upload(c, video, key=None, ui=True)
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        j = c.get(f"/ui/api/jobs/{job_id}").json()
        assert "queue_position" in j or j["status"] == "done"
        j = wait_done(c, job_id, key=None, ui=True)
        assert j["status"] == "done"
        assert c.get("/health").json()["status"] == "ok"
        assert c.get("/").status_code == 200
        assert c.get("/live.html").status_code == 200
        info = c.get("/ui/api/info").json()
        assert len(info["types"]) >= 15 and "features" in info
        assert len(c.get("/ui/api/rules").json()["types"]) >= 15
        assert c.get("/ui/api/jobs").json()["jobs"][0]["job_id"] == job_id
        stats = c.get("/ui/api/stats").json()
        assert stats["jobs"]["done"] >= 1 and "pool" in stats
        # feedback -> csv
        r = c.post(f"/ui/api/jobs/{job_id}/feedback", json={"violation_index": 0, "decision": "reject", "comment": "x"})
        assert r.status_code == 200
        csv = c.get("/ui/api/feedback.csv").text
        assert job_id in csv and "reject" in csv
        assert c.post(f"/ui/api/jobs/{job_id}/feedback", json={"decision": "bogus"}).status_code == 422
        # report
        for lang, title in (("en", "Cash-desk video check"), ("ru", "Проверка видео с кассы"), ("kk", "Касса бейнежазбасын тексеру")):
            r = c.get(f"/ui/api/jobs/{job_id}/report.html?lang={lang}")
            assert r.status_code == 200 and title in r.text and f'<html lang="{lang}">' in r.text
        assert "Проверка видео с кассы" in c.get(f"/ui/api/jobs/{job_id}/report.html").text
        assert "Cash-desk video check" in c.get(f"/ui/api/jobs/{job_id}/report.html", headers={"Accept-Language": "en-US,en;q=0.9"}).text
        assert c.get("/metrics").status_code == 200
        assert b"cashguard_jobs_total" in c.get("/metrics").content
        assert c.get("/version").json()["analyzer"] == "mock"


def test_ui_requires_key_when_configured(app_factory, video):
    with app_factory(UI_REQUIRE_KEY="1") as (c, st):
        assert c.get("/ui/api/info").status_code == 401
        assert c.get("/ui/api/info?key=test-key").status_code == 200
        assert c.get("/ui/api/info", headers={"X-API-Key": "test-key"}).status_code == 200


def test_sse_progress_stream(app_factory, video):
    with app_factory(MOCK_DELAY="0.6") as (c, st):
        wait_ready(c)
        job_id = upload(c, video).json()["job_id"]
        events = []
        with c.stream("GET", f"/ui/api/jobs/{job_id}/events") as r:
            assert r.status_code == 200
            for line in r.iter_lines():
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
                if events and events[-1] in ("done", "failed"):
                    break
        assert events[0] == "snapshot"
        assert "progress" in events
        assert events[-1] == "done"


def test_rate_limit(app_factory, video):
    with app_factory(RATE_LIMIT_PER_MIN="2") as (c, st):
        codes = [upload(c, video).status_code for _ in range(4)]
        assert codes[:2] == [200, 200] and 429 in codes[2:]


def test_admin_keys_and_roles(app_factory, video):
    with app_factory() as (c, st):
        wait_ready(c)
        assert c.get("/admin/api/keys", headers={"X-API-Key": "test-key"}).status_code == 403
        r = c.post("/admin/api/keys", headers={"X-API-Key": "admin-key"}, json={"role": "jury", "name": "jury-2"})
        assert r.status_code == 201
        key2 = r.json()["key"]
        assert upload(c, video, key=key2).status_code == 200
        assert c.delete(f"/admin/api/keys/{r.json()['id']}", headers={"X-API-Key": "admin-key"}).status_code == 200
        assert upload(c, video, key=key2).status_code == 401
        cfg = c.get("/admin/api/config", headers={"X-API-Key": "admin-key"}).json()
        assert cfg["settings"]["api_key"] == "***" and "routing" in cfg["alerts_policy"]
        assert c.get("/admin/api/audit", headers={"X-API-Key": "admin-key"}).json()["audit"]
        assert c.get("/admin/api/workers", headers={"X-API-Key": "admin-key"}).json()["workers"]


def test_retention_deletes_video_but_keeps_result(app_factory, video):
    import time
    from pathlib import Path
    with app_factory(VIDEO_TTL_SEC="1") as (c, st):
        wait_ready(c)
        job_id = upload(c, video).json()["job_id"]
        wait_done(c, job_id)
        row = st.jobs.get(job_id)
        assert Path(row["upload_path"]).exists()
        time.sleep(1.2)
        st.retention.run_once()
        row = st.jobs.get(job_id)
        assert row["upload_path"] is None
        j = c.get(f"/api/v1/jobs/{job_id}", headers={"X-API-Key": "test-key"}).json()
        assert j["status"] == "done" and j["verdict"] in ("violation", "no_violation")


def test_alerts_created_for_violations(app_factory, video):
    with app_factory() as (c, st):
        wait_ready(c)
        j = wait_done(c, upload(c, video).json()["job_id"])
        n = len(j["violations"])
        alerts = c.get("/ui/api/alerts").json()["alerts"]
        assert len(alerts) == n
        if n:
            a = alerts[0]
            assert a["state"] == "open" and a["severity"] in ("critical", "high", "medium", "low")
            r = c.post(f"/ui/api/alerts/{a['id']}/ack", json={"decision": "false_positive", "comment": "test"})
            assert r.status_code == 200 and r.json()["state"] == "false_positive"
            assert c.get("/ui/api/alerts/summary").json()["by_state"]["false_positive"] == 1
            assert f"alert #{a['id']} false positive" in c.get("/ui/api/feedback.csv").text


def test_job_video_and_feedback_list(app_factory, video):
    from pathlib import Path
    with app_factory() as (c, st):
        wait_ready(c)
        job_id = upload(c, video).json()["job_id"]
        wait_done(c, job_id)
        r = c.get(f"/ui/api/jobs/{job_id}/video")
        assert r.status_code == 200 and r.headers["content-type"].startswith("video/")
        assert len(r.content) == Path(video).stat().st_size
        c.post(f"/ui/api/jobs/{job_id}/feedback", json={"violation_index": 0, "decision": "confirm"})
        fb = c.get(f"/ui/api/jobs/{job_id}/feedback").json()["feedback"]
        assert fb and fb[0]["decision"] == "confirm" and fb[0]["violation_index"] == 0
        # after retention the video is gone but the UI still gets a clean 404
        st.db.update("jobs", "job_id", job_id, {"finished_at": 0})
        st.retention.run_once()
        assert c.get(f"/ui/api/jobs/{job_id}/video").status_code == 404
        assert c.get("/").status_code == 200 and "app.js" in c.get("/").text
        assert c.get("/app.js").status_code == 200 and c.get("/app.css").status_code == 200
        assert c.get("/live.html").status_code == 200


def test_delete_and_cancel_jobs(app_factory, video, video2):
    from pathlib import Path
    with app_factory(MOCK_DELAY="20", DEDUP="0") as (c, st):
        wait_ready(c)
        running = upload(c, video).json()["job_id"]
        queued = upload(c, video2).json()["job_id"]
        import time
        time.sleep(0.5)
        assert st.jobs.get(running)["status"] == "running"
        assert st.jobs.get(queued)["status"] == "queued"
        up = Path(st.jobs.get(queued)["upload_path"])
        assert c.delete(f"/ui/api/jobs/{queued}").status_code == 200
        assert not up.exists() and st.pool.position(queued) is None
        assert c.delete(f"/ui/api/jobs/{running}").status_code == 200
        assert c.get(f"/ui/api/jobs/{running}").status_code == 404
        assert c.delete(f"/ui/api/jobs/{running}").status_code == 404
        wait_ready(c)
        assert st.pool.stats()["running"] == []
        assert c.get("/ui/api/jobs").json()["jobs"] == []
    with app_factory(MOCK_DELAY="0.2") as (c, st):
        wait_ready(c)
        jid = upload(c, video).json()["job_id"]
        j = wait_done(c, jid)
        if j["violations"]:
            assert c.get("/ui/api/alerts").json()["alerts"]
        res = Path(st.jobs.get(jid)["result_path"])
        assert c.delete(f"/ui/api/jobs/{jid}").status_code == 200
        assert not res.exists()
        assert c.get("/ui/api/alerts").json()["alerts"] == []
        audit = c.get("/admin/api/audit", headers={"X-API-Key": "admin-key"}).json()["audit"]
        assert any(a["action"] == "job.delete" and a["entity"] == jid for a in audit)


def test_review_decisions_and_clear(app_factory, video):
    with app_factory(MOCK_DELAY="0.2") as (c, st):
        wait_ready(c)
        jid = upload(c, video).json()["job_id"]
        wait_done(c, jid)
        c.post(f"/ui/api/jobs/{jid}/feedback", json={"violation_index": 0, "decision": "confirm"})
        assert c.get(f"/ui/api/jobs/{jid}").json()["decisions"] == {"0": "confirm"}
        row = c.get("/ui/api/jobs").json()["jobs"][0]
        assert row["reviewed"] == 1 and row["confirmed"] == 1
        c.post(f"/ui/api/jobs/{jid}/feedback", json={"violation_index": 0, "decision": "clear"})
        assert c.get(f"/ui/api/jobs/{jid}").json()["decisions"] == {}
        c.post(f"/ui/api/jobs/{jid}/feedback", json={"violation_index": 0, "decision": "reject"})
        r = c.get(f"/ui/api/jobs/{jid}/report.html?lang=en")
        assert r.status_code == 200 and "Not a violation" in r.text and "Reviewed by" in r.text
        assert "Не нарушение" in c.get(f"/ui/api/jobs/{jid}/report.html?lang=ru").text
        assert c.get("/").headers.get("cache-control") == "no-cache"


def test_review_decision_closes_alert(app_factory, video):
    with app_factory(ANALYZER="backend.tests.fake_analyzers:quick") as (c, st):
        wait_ready(c)
        jid = upload(c, video).json()["job_id"]
        wait_done(c, jid)
        a = c.get("/ui/api/alerts").json()["alerts"][0]
        assert a["state"] == "open"
        c.post(f"/ui/api/jobs/{jid}/feedback", json={"violation_index": 0, "decision": "reject"})
        assert c.get("/ui/api/alerts").json()["alerts"][0]["state"] == "false_positive"
        c.post(f"/ui/api/jobs/{jid}/feedback", json={"violation_index": 0, "decision": "clear"})
        assert c.get("/ui/api/alerts").json()["alerts"][0]["state"] == "open"
        c.post(f"/ui/api/jobs/{jid}/feedback", json={"violation_index": 0, "decision": "confirm"})
        assert c.get("/ui/api/alerts").json()["alerts"][0]["state"] == "resolved"
        fb = c.get(f"/ui/api/jobs/{jid}/feedback").json()["feedback"]
        assert len(fb) == 3


def test_i18n_tables_are_complete():
    import json
    import re
    from pathlib import Path

    from backend.app.i18n import REPORT, Translator
    from ml import kb

    for lang in ("ru", "kk"):
        assert set(REPORT[lang]) == set(REPORT["en"])
    static = Path(__file__).resolve().parents[1] / "static"
    data = json.loads((static / "i18n-kb.json").read_text(encoding="utf-8"))
    for code in kb.type_codes():
        for lang in ("en", "kk"):
            entry = data["types"][code][lang]
            assert entry["name"] and entry["visual"] and entry["why"], (code, lang)
            if kb.rule_of(code).get("caveat"):
                assert entry.get("caveat"), (code, lang)
    srcs = kb.load_kb()["sources"]
    for sid, src in srcs.items():
        assert data["sources"][sid]["match"] in (src.get("url") or ""), sid
    js = (static / "i18n.js").read_text(encoding="utf-8")
    blocks = re.split(r"\n  (?:en|ru|kk): \{", js)[1:4]
    keys = [set(re.findall(r"'([a-zA-Z_.]+)':", b.split("\n  },")[0])) for b in blocks]
    assert keys[0] == keys[1] == keys[2] and len(keys[0]) > 150
    t = Translator("en")
    v = {"type": "Сейф", "type_code": "T03", "description": "Сейф открыт. Это может указывать на нарушение: x. Основание: п. 20 — y.",
         "rule": {"caveat": None}}
    assert t.type_name(v) == "Safe left open and unattended"
    assert t.description(v)["observed"] == "Сейф открыт" and t.description(v)["why"]
    assert t.point("п. 71 пп. 9") == "para. 71 subpara. 9" and Translator("kk").point("п. 20") == "20-тармақ"
    assert Translator("kk").doc({"document": "x", "url": "https://adilet.zan.kz/rus/docs/V1900019680"}).startswith("Кассалық")
