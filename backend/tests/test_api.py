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
        info = c.get("/ui/api/info").json()
        assert len(info["types"]) >= 15 and "features" in info
        assert len(c.get("/ui/api/rules").json()["types"]) >= 15
        assert c.get("/ui/api/jobs").json()["jobs"][0]["job_id"] == job_id
        stats = c.get("/ui/api/stats").json()
        assert stats["jobs"]["done"] >= 1 and "pool" in stats
        # findings -> decision -> csv
        f = c.get(f"/ui/api/jobs/{job_id}").json()["findings"][0]
        r = c.post(f"/ui/api/findings/{f['id']}/decision", json={"decision": "reject", "comment": "x"})
        assert r.status_code == 200 and r.json()["decision"] == "reject"
        csv = c.get("/ui/api/findings.csv").text
        assert job_id in csv and "reject" in csv
        assert c.post(f"/ui/api/findings/{f['id']}/decision", json={"decision": "bogus"}).status_code == 422
        # report
        for lang, title in (("en", "Cash-desk video check"), ("ru", "Проверка видео с кассы"), ("kk", "Касса бейнежазбасын тексеру")):
            r = c.get(f"/ui/api/jobs/{job_id}/report.html?lang={lang}")
            assert r.status_code == 200 and title in r.text and f'<html lang="{lang}">' in r.text
        assert "Проверка видео с кассы" in c.get(f"/ui/api/jobs/{job_id}/report.html").text
        assert "Cash-desk video check" in c.get(f"/ui/api/jobs/{job_id}/report.html", headers={"Accept-Language": "en-US,en;q=0.9"}).text
        assert c.get("/metrics").status_code == 200
        assert b"cashguard_jobs_total" in c.get("/metrics").content
        assert c.get("/version").json()["analyzer"] == "mock"


def test_ui_requires_login_when_configured(app_factory, video):
    from backend.tests.conftest import login
    with app_factory(AUTH_REQUIRED="1") as (c, st):
        assert c.get("/ui/api/info").status_code == 401
        assert c.get("/ui/api/info", headers={"X-API-Key": "admin-key"}).status_code == 200
        assert c.post("/ui/api/auth/login", json={"login": "operator", "password": "wrong"}).status_code == 401
        u = login(c, "operator", "op123")
        assert u["role"] == "operator" and u["name"] == "Operator One"
        me = c.get("/ui/api/auth/me").json()
        assert me["user"]["login"] == "operator" and me["user"]["role"] == "operator"
        assert c.get("/ui/api/info").status_code == 200
        assert c.get("/ui/api/users").status_code == 403           # operators cannot manage users
        assert c.post("/ui/api/cameras", json={"name": "x", "url": "0"}).status_code == 403
        assert c.post("/ui/api/auth/logout").status_code == 200
        assert c.get("/ui/api/info").status_code == 401
        # admin: user management
        login(c, "admin", "admin123")
        users = c.get("/ui/api/users").json()["users"]
        assert {u["login"] for u in users} == {"admin", "operator", "supervisor"}
        r = c.post("/ui/api/users", json={"login": "op2", "password": "pass1234", "role": "operator", "name": "Op Two",
                                          "camera_ids": ["cam1"]})
        assert r.status_code == 201 and r.json()["camera_ids"] == ["cam1"]
        uid = r.json()["id"]
        assert c.patch(f"/ui/api/users/{uid}", json={"active": False}).status_code == 200
        admin_id = next(u["id"] for u in users if u["login"] == "admin")
        assert c.patch(f"/ui/api/users/{admin_id}", json={"active": False}).status_code == 409
        c.post("/ui/api/auth/logout")
        assert c.post("/ui/api/auth/login", json={"login": "op2", "password": "pass1234"}).status_code == 401


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
    with app_factory(JURY_VIDEO_TTL_SEC="1", DEDUP="0") as (c, st):
        wait_ready(c)
        job_id = upload(c, video).json()["job_id"]                 # jury upload: deleted after the TTL
        ui_job = upload(c, video, key=None, ui=True).json()["job_id"]  # operator upload: kept
        wait_done(c, job_id)
        wait_done(c, ui_job, ui=True)
        row = st.jobs.get(job_id)
        assert Path(row["upload_path"]).exists()
        time.sleep(1.2)
        st.retention.run_once()
        row = st.jobs.get(job_id)
        assert row["upload_path"] is None
        assert Path(st.jobs.get(ui_job)["upload_path"]).exists()
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
            assert a["finding_id"] is not None


def test_job_video_and_finding_history(app_factory, video):
    from pathlib import Path
    with app_factory() as (c, st):
        wait_ready(c)
        job_id = upload(c, video).json()["job_id"]
        wait_done(c, job_id)
        r = c.get(f"/ui/api/jobs/{job_id}/video")
        assert r.status_code == 200 and r.headers["content-type"].startswith("video/")
        assert len(r.content) == Path(video).stat().st_size
        fid = c.get(f"/ui/api/jobs/{job_id}").json()["findings"][0]["id"]
        c.post(f"/ui/api/findings/{fid}/decision", json={"decision": "confirm"})
        f = c.get(f"/ui/api/findings/{fid}").json()
        assert f["decision"] == "confirm" and f["history"][-1]["action"] == "decide" and f["frames"]
        assert f["video_url"] and f["siblings"]
        # jury videos go after the TTL; the UI then gets a clean 404
        st.db.update("jobs", "job_id", job_id, {"finished_at": 0})
        st.retention.run_once()
        assert c.get(f"/ui/api/jobs/{job_id}/video").status_code == 404
        assert c.get("/").status_code == 200


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
        fid = c.get(f"/ui/api/jobs/{jid}").json()["findings"][0]["id"]
        c.post(f"/ui/api/findings/{fid}/decision", json={"decision": "confirm"})
        assert c.get(f"/ui/api/jobs/{jid}").json()["decisions"] == {"0": "confirm"}
        row = c.get("/ui/api/jobs").json()["jobs"][0]
        assert row["reviewed"] == 1 and row["confirmed"] == 1
        c.post(f"/ui/api/findings/{fid}/decision", json={"decision": None})
        assert c.get(f"/ui/api/jobs/{jid}").json()["decisions"] == {}
        c.post(f"/ui/api/findings/{fid}/decision", json={"decision": "reject"})
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
        assert a["state"] == "open" and a["finding_id"]
        fid = a["finding_id"]
        c.post(f"/ui/api/findings/{fid}/decision", json={"decision": "reject"})
        assert c.get("/ui/api/alerts").json()["alerts"][0]["state"] == "false_positive"
        c.post(f"/ui/api/findings/{fid}/decision", json={"decision": None})
        assert c.get("/ui/api/alerts").json()["alerts"][0]["state"] == "open"
        c.post(f"/ui/api/findings/{fid}/decision", json={"decision": "confirm"})
        assert c.get("/ui/api/alerts").json()["alerts"][0]["state"] == "resolved"
        assert len(c.get(f"/ui/api/findings/{fid}").json()["history"]) == 3


def test_i18n_tables_are_complete():
    import json
    import re
    from pathlib import Path

    from backend.app.i18n import REPORT, Translator
    from ml import kb

    for lang in ("ru", "kk"):
        assert set(REPORT[lang]) == set(REPORT["en"])
    data = json.loads((Path(__file__).resolve().parents[1] / "i18n-kb.json").read_text(encoding="utf-8"))
    for code in kb.type_codes():
        for lang in ("en", "kk"):
            entry = data["types"][code][lang]
            assert entry["name"] and entry["visual"] and entry["why"], (code, lang)
            if kb.rule_of(code).get("caveat"):
                assert entry.get("caveat"), (code, lang)
    srcs = kb.load_kb()["sources"]
    for sid, src in srcs.items():
        assert data["sources"][sid]["match"] in (src.get("url") or ""), sid
    ts = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n" / "strings.ts").read_text(encoding="utf-8")
    blocks = re.split(r"\n  (?:en|ru|kk): \{\n", ts)[1:4]
    keys = [set(re.findall(r"'([a-zA-Z_.]+)':", b.split("\n  },")[0])) for b in blocks]
    assert keys[0] == keys[1] == keys[2] and len(keys[0]) > 150
    t = Translator("en")
    v = {"type": "Сейф", "type_code": "T03", "description": "Сейф открыт. Это может указывать на нарушение: x. Основание: п. 20 — y.",
         "rule": {"caveat": None}}
    assert t.type_name(v) == "Safe left open and unattended"
    assert t.description(v)["observed"] == "Сейф открыт" and t.description(v)["why"]
    assert t.point("п. 71 пп. 9") == "para. 71 subpara. 9" and Translator("kk").point("п. 20") == "20-тармақ"
    assert Translator("kk").doc({"document": "x", "url": "https://adilet.zan.kz/rus/docs/V1900019680"}).startswith("Кассалық")


def test_findings_review_workflow(app_factory, video):
    from backend.tests.conftest import login
    with app_factory(ANALYZER="backend.tests.fake_analyzers:quick", AUTH_REQUIRED="1") as (c, st):
        wait_ready(c)
        login(c, "operator", "op123")
        jid = upload(c, video, key=None, ui=True).json()["job_id"]
        job = wait_done(c, jid, ui=True)
        assert job["created_by"] == "operator"
        f = job["findings"][0]
        ai = c.get(f"/ui/api/findings/{f['id']}").json()["description_ai"]
        # operator rewords the description, then rejects the finding
        r = c.patch(f"/ui/api/findings/{f['id']}/description", json={"text": "Кассир просто поправил стул, денег на столе нет"})
        assert r.status_code == 200 and r.json()["edited"] and r.json()["description_ai"] == ai
        r = c.post(f"/ui/api/findings/{f['id']}/decision", json={"decision": "reject", "comment": "ложное"})
        assert r.json()["decision"] == "reject" and r.json()["decided_by"] == "operator"
        assert c.post(f"/ui/api/findings/{f['id']}/verify", json={"result": "agree"}).status_code == 403
        # supervisor sees the disagreement queue and verifies
        c.post("/ui/api/auth/logout")
        login(c, "supervisor", "sv123")
        lst = c.get("/ui/api/findings?decision=reject&verified=false").json()
        assert lst["total"] == 1 and lst["findings"][0]["edited"] and lst["counts"]["rejected_unverified"] == 1
        r = c.post(f"/ui/api/findings/{f['id']}/verify", json={"result": "disagree", "comment": "видно наличные"})
        assert r.status_code == 200 and r.json()["verified"] and r.json()["verify_result"] == "disagree"
        full = c.get(f"/ui/api/findings/{f['id']}").json()
        assert full["verified_by_name"] == "Super Visor" and [h["action"] for h in full["history"]] == ["edit", "decide", "verify"]
        assert c.get("/ui/api/findings?verified=true").json()["total"] == 1
        # a changed operator decision resets verification
        c.post("/ui/api/auth/logout")
        login(c, "operator", "op123")
        r = c.post(f"/ui/api/findings/{f['id']}/decision", json={"decision": "confirm"})
        assert r.json()["decision"] == "confirm" and not r.json()["verified"]
        rep = c.get(f"/ui/api/jobs/{jid}/report.html?lang=ru").text
        assert "Кассир просто поправил стул" in rep
        c.post("/ui/api/auth/logout")
        assert c.get("/ui/api/findings.csv").status_code == 401


def test_camera_alert_creates_finding_with_frames(app_factory, video):
    import time
    with app_factory(LIVE_FPS="8") as (c, st):
        wait_ready(c)
        cam = c.post("/ui/api/cameras", json={"name": "Касса 1", "url": str(video), "fps": 8}).json()
        found = None
        for _ in range(100):
            lst = c.get("/ui/api/findings?source=camera").json()
            if lst["findings"]:
                found = lst["findings"][0]
                break
            time.sleep(0.2)
        assert found, "no finding from the mock camera"
        assert found["camera_id"] == cam["id"] and found["type_code"] in ("T13", "T15", "T14", "T01")
        f = c.get(f"/ui/api/findings/{found['id']}").json()
        assert f["frames"] and f["sequence"] and f["t_sec"] is not None and f["alert"]["id"] == f["alert_id"]
        assert c.get(f"/ui/api/findings/{found['id']}/frames/0.jpg").status_code == 200
        if f["clip_url"]:
            assert c.get(f["clip_url"]).status_code == 200
        c.post(f"/ui/api/findings/{found['id']}/decision", json={"decision": "confirm"})
        assert c.get(f"/ui/api/alerts/{f['alert_id']}" if False else "/ui/api/alerts").json()["alerts"][0]["state"] in ("resolved", "open")
        assert c.delete(f"/ui/api/cameras/{cam['id']}").status_code == 200


def test_quality_stats_thresholds_and_dataset(app_factory, video):
    import io
    import time
    import zipfile
    from backend.tests.conftest import login
    with app_factory(ANALYZER="backend.tests.fake_analyzers:quick", AUTH_REQUIRED="1", QUALITY_MIN_SAMPLES="6") as (c, st):
        wait_ready(c)
        login(c, "operator", "op123")
        jid = upload(c, video, key=None, ui=True).json()["job_id"]
        f = wait_done(c, jid, ui=True)["findings"][0]
        assert c.get("/ui/api/quality").status_code == 403
        c.post(f"/ui/api/findings/{f['id']}/decision", json={"decision": "reject"})
        # a jury upload also gets a finding, but it never reaches the dataset
        rj = upload(c, video, key="test-key"); assert rj.status_code == 200, rj.text
        jury = rj.json()["job_id"]
        assert jury == jid or wait_done(c, jury)["status"] == "done"
        # synthetic history: T13 is rejected whenever the model was unsure, T02 is solid
        now = time.time()
        for i in range(8):
            conf = 0.52 + 0.05 * i
            st.db.insert("findings", {"source": "camera", "camera_id": "cam1", "camera_name": "Касса 1", "type_code": "T13",
                                      "type_name": "Личные вещи", "t_sec": 1.0, "confidence": conf, "description_ai": "x",
                                      "rule": {}, "decision": "confirm" if conf >= 0.7 else "reject", "decided_by": "operator",
                                      "decided_at": now, "verified": 1, "verify_result": "agree", "verified_by": "supervisor",
                                      "verified_at": now, "created_at": now - 86400 * (i % 3), "updated_at": now})
        st.quality.invalidate()
        c.post("/ui/api/auth/logout")
        login(c, "supervisor", "sv123")
        r = c.post(f"/ui/api/findings/{f['id']}/verify", json={"result": "disagree", "comment": "видно наличные"})
        assert r.status_code == 200
        q = c.get("/ui/api/quality?days=30").json()
        s = q["summary"]
        assert s["decided"] == 9 and s["verified"] == 9 and s["flagged"] == 1 and s["basis"] == "verified"
        assert s["accuracy"] == round(5 / 9, 3)  # 4 T13 confirmed + the overruled rejection
        t13 = next(x for x in q["by_type"] if x["type_code"] == "T13")
        assert t13["decided"] == 8 and t13["confirm_rate"] == 0.5
        assert t13["threshold"]["status"] == "raised" and t13["threshold"]["applied"] == 0.65
        assert "T13" in q["thresholds"]["raised"]
        op = next(x for x in q["operators"] if x["login"] == "operator")
        assert op["decided"] == 9 and op["rejected"] == 5 and op["disagreed"] == 1 and op["name"] == "Operator One"
        assert len(q["weekly"]) == 8 and q["weekly"][-1]["decided"] >= 7
        # the raised threshold marks weak findings and downgrades their alerts
        assert st.quality.below_threshold("T13", 0.55) and not st.quality.below_threshold("T13", 0.67)
        assert not st.quality.below_threshold("T02", 0.55)
        ev = st._apply_threshold({"type_code": "T13", "confidence": 0.55, "source": "live"})
        assert ev["severity"] == "low" and ev["below_threshold"]
        lst = c.get("/ui/api/findings?type_code=T13").json()["findings"]
        assert sum(1 for x in lst if x["below_threshold"]) == 3
        # dataset: labels + frames, jury finding excluded
        r = c.get("/ui/api/quality/dataset.zip")
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        z = zipfile.ZipFile(io.BytesIO(r.content))
        rows = [json.loads(l) for l in z.read("labels.jsonl").decode("utf-8").splitlines()]
        assert len(rows) == 9 and all(x["job_id"] != jury or jury == jid for x in rows)
        mine = next(x for x in rows if x["finding_id"] == f["id"])
        assert mine["label"] == 1 and mine["label_source"] == "supervisor" and mine["operator_decision"] == "reject"
        assert mine["frames"] and z.read(mine["frames"][0])[:2] == b"\xff\xd8"
        assert "README.txt" in z.namelist() and "labels.csv" in z.namelist()
