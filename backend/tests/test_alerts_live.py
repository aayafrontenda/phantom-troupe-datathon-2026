"""Alert engine (dedup, escalation, delivery, ack) and live mode (browser WS, file-backed camera)."""
from __future__ import annotations

import base64
import json
import time

import cv2
import numpy as np

from backend.tests.conftest import make_app, wait_ready


def _event(**kw) -> dict:
    base = {"source": "camera", "camera_id": "cam1", "camera_name": "Касса 1", "type_code": "T03",
            "type_name": "Сейф оставлен открытым", "message": "дверца сейфа открыта", "t_sec": 12.0}
    base.update(kw)
    return base


def test_engine_dedup_cooldown_and_escalation(tmp_path):
    with make_app(tmp_path) as (c, st):
        eng = st.alerts
        a1 = eng.handle(_event())
        assert a1 and a1["severity"] == "critical" and a1["state"] == "open" and a1["escalate_at"]
        assert eng.handle(_event()) is None                       # inside cooldown -> counted, not re-sent
        assert eng.get(a1["id"])["count"] == 2
        other = eng.handle(_event(type_code="T14", type_name="Еда"))
        assert other["severity"] == "low" and other["escalate_at"] is None
        # critical goes to operator and supervisor immediately
        roles = {d["target"] for d in eng.get(a1["id"])["deliveries"]}
        assert "ui" in roles or "log" in roles
        # escalation: pretend the timer expired
        n = eng.escalate_due(now=time.time() + 10_000)
        assert n == 1
        esc = eng.get(a1["id"])
        assert esc["escalation_level"] == 1
        # ack stops further escalation
        acked = eng.ack(a1["id"], by="tester", decision="acknowledged")
        assert acked["state"] == "acknowledged" and acked["escalate_at"] is None
        assert eng.escalate_due(now=time.time() + 100_000) == 0
        # a new alert after the window is a new row
        time.sleep(0.05)
        st.db.update("alerts", "id", a1["id"], {"created_at": time.time() - 10_000})
        a3 = eng.handle(_event())
        assert a3 and a3["id"] != a1["id"]
        s = eng.summary()
        assert s["open"] == 2 and s["by_state"]["acknowledged"] == 1 and s["mtta_sec"] >= 0


def test_webhook_signed_delivery(tmp_path):
    with make_app(tmp_path, ALERT_WEBHOOK_URL="http://example.invalid/hook", ALERT_WEBHOOK_SECRET="s3cret") as (c, st):
        received = []
        st.alerts.channels["webhook"].post = lambda url, body, headers: received.append((url, body, headers))
        st.alerts.policy["channels"]["operator"] = ["web", "webhook"]
        a = st.alerts.handle(_event(type_code="T02", type_name="Наличные"))
        for _ in range(50):
            if received:
                break
            time.sleep(0.05)
        assert received, "webhook not called"
        url, body, headers = received[0]
        assert url.endswith("/hook") and headers["X-Signature"].startswith("sha256=")
        payload = json.loads(body)
        assert payload["alert"]["id"] == a["id"] and payload["role"] == "operator"
        import hashlib
        import hmac
        assert headers["X-Signature"] == "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        for _ in range(50):
            d = [x for x in st.alerts.get(a["id"])["deliveries"] if x["channel"] == "webhook"]
            if d and d[0]["status"] == "sent":
                break
            time.sleep(0.05)
        assert d[0]["status"] == "sent"


def test_alert_sse_stream_and_api(tmp_path):
    with make_app(tmp_path) as (c, st):
        a = st.alerts.handle(_event(camera_id="cam9"))
        lst = c.get("/ui/api/alerts?state=open&camera_id=cam9").json()["alerts"]
        assert lst and lst[0]["id"] == a["id"]
        with c.stream("GET", "/ui/api/alerts/stream?max=1") as r:
            got = None
            for line in r.iter_lines():
                if line.startswith("data:"):
                    got = json.loads(line[5:])
                    break
        assert got and got["type"] == "alert" and got["alert"]["id"] == a["id"]
        assert c.post(f"/ui/api/alerts/{a['id']}/ack", json={"decision": "resolved"}).json()["state"] == "resolved"
        assert c.post("/ui/api/alerts/999999/ack", json={"decision": "resolved"}).status_code == 404


def _jpeg(i: int) -> bytes:
    img = np.full((240, 320, 3), 60, np.uint8)
    cv2.rectangle(img, (10 + i * 15, 60), (90 + i * 15, 180), (200, 200, 200), -1)
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


def test_browser_live_websocket_mock(tmp_path):
    with make_app(tmp_path) as (c, st):
        with c.websocket_connect("/ui/api/live") as ws:
            ws.send_text(json.dumps({"ping": 1}))
            assert "pong" in ws.receive_json()
            seen_alert = False
            for i in range(12):
                if i % 2:
                    ws.send_bytes(_jpeg(i))
                else:
                    ws.send_text(json.dumps({"image": "data:image/jpeg;base64," + base64.b64encode(_jpeg(i)).decode()}))
                msg = ws.receive_json()
                assert "detections" in msg and msg["size"] == [320, 240]
                seen_alert = seen_alert or bool(msg["alerts"])
            assert seen_alert, "mock motion rule never fired"
        alerts = c.get("/ui/api/alerts").json()["alerts"]
        assert alerts and alerts[0]["camera_id"] == "browser"


def test_file_camera_streams_frames(tmp_path, video):
    with make_app(tmp_path, LIVE_FPS="8", AUTH_REQUIRED="1") as (c, st):
        wait_ready(c)
        admin = {"X-API-Key": "admin-key"}
        assert c.post("/ui/api/cameras", json={"name": "Касса 1", "url": str(video)}).status_code == 401
        assert c.post("/ui/api/cameras", headers={"X-API-Key": "test-key"},
                      json={"name": "Касса 1", "url": str(video)}).status_code == 403
        c.headers.update(admin)
        r = c.post("/ui/api/cameras", headers=admin, json={"name": "Касса 1", "url": str(video), "id": "cam1", "fps": 8})
        assert r.status_code == 201, r.text
        for _ in range(100):
            cam = c.get("/ui/api/cameras/cam1").json()
            if cam["state"]["status"] == "online" and cam["state"]["frames"] >= 3:
                break
            time.sleep(0.1)
        assert cam["state"]["status"] == "online" and cam["state"]["frames"] >= 3
        snap = c.get("/ui/api/cameras/cam1/snapshot.jpg")
        assert snap.status_code == 200 and snap.content[:2] == b"\xff\xd8"
        with c.websocket_connect("/ui/api/cameras/cam1/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "frame" and base64.b64decode(msg["frame"])[:2] == b"\xff\xd8"
        assert c.get("/health").json()["cameras_online"] == 1
        stats = c.get("/ui/api/stats").json()
        assert stats["cameras"][0]["id"] == "cam1"
        r = c.patch("/ui/api/cameras/cam1", headers=admin, json={"enabled": False})
        assert r.status_code == 200 and r.json()["enabled"] is False
        time.sleep(0.3)
        assert c.get("/ui/api/cameras/cam1").json()["state"]["status"] == "stopped"
        assert c.delete("/ui/api/cameras/cam1", headers=admin).status_code == 200
        assert c.get("/ui/api/cameras/cam1").status_code == 404
        # unreachable source -> offline, not crash
        r = c.post("/ui/api/cameras", headers=admin, json={"name": "bad", "url": "rtsp://127.0.0.1:1/none", "id": "bad"})
        assert r.status_code == 201
        for _ in range(100):
            if c.get("/ui/api/cameras/bad").json()["state"]["status"] == "offline":
                break
            time.sleep(0.1)
        assert c.get("/ui/api/cameras/bad").json()["state"]["status"] == "offline"


def test_telegram_bot_notifies_without_decisions(tmp_path, video):
    import json as _json

    import httpx

    from backend.tests.conftest import login, upload, wait_done
    calls: list[tuple[str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        method = req.url.path.rsplit("/", 1)[-1]
        if req.headers.get("content-type", "").startswith("application/json"):
            body = _json.loads(req.content or b"{}")
        else:
            body = {k: _form(req, k) for k in ("chat_id", "caption", "reply_markup")}
        calls.append((method, body))
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"username": "phantomguard_test_bot"}})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    def sent(chat) -> list[dict]:
        return [b for m, b in calls if m in ("sendMessage", "sendPhoto") and str(b.get("chat_id")) == str(chat)]

    def wait(pred, n=100):
        for _ in range(n):
            if pred():
                return True
            time.sleep(0.05)
        return False

    def link(c, chat: int, username: str, lang: str = "ru"):
        code = c.post("/ui/api/auth/telegram/link").json()["url"].split("start=")[1]
        bot.handle_update({"update_id": chat, "message": {"chat": {"id": chat, "type": "private"}, "text": f"/start {code}",
                                                          "from": {"id": chat, "username": username, "language_code": lang}}})

    with make_app(tmp_path, TELEGRAM_BOT_TOKEN="123:abc", AUTH_REQUIRED="1", DEDUP="0", TELEGRAM_POLL="0",
                  PUBLIC_URL="https://cg.example.kz", ANALYZER="backend.tests.fake_analyzers:quick") as (c, st):
        bot = st.alerts.telegram
        bot.transport = httpx.MockTransport(handler)
        # supervisor links first
        login(c, "supervisor", "sv123")
        link(c, 777, "boss", "en")
        assert "Super Visor" in sent(777)[-1]["text"] and "rejected" in sent(777)[-1]["text"]
        c.post("/ui/api/auth/logout")
        # operator: a bad code is refused, a fresh one links the account
        login(c, "operator", "op123")
        assert c.get("/ui/api/auth/telegram").json() == {"enabled": True, "bot": "phantomguard_test_bot", "linked": False,
                                                        "telegram": None, "photos": True}
        bot.handle_update({"update_id": 1, "message": {"chat": {"id": 501, "type": "private"}, "text": "/start bogus",
                                                       "from": {"id": 501}}})
        assert "устарела" in sent(501)[-1]["text"]
        link(c, 501, "aigerim")
        assert "Operator One" in sent(501)[-1]["text"]
        assert c.get("/ui/api/auth/telegram").json()["telegram"]["username"] == "aigerim"
        # the operator's video check -> "possible violation found" with a frame and only an "Open" link button
        jid = upload(c, video, key=None, ui=True).json()["job_id"]
        fid = wait_done(c, jid, ui=True)["findings"][0]["id"]
        assert wait(lambda: any(m == "sendPhoto" and str(b["chat_id"]) == "501" for m, b in calls)), calls
        photo = next(b for m, b in calls if m == "sendPhoto" and str(b["chat_id"]) == "501")
        assert "Найдено возможное нарушение" in photo["caption"]
        kb = _json.loads(photo["reply_markup"])["inline_keyboard"]
        assert kb == [[{"text": "Открыть в PhantomGuard", "url": f"https://cg.example.kz/findings/{fid}"}]]
        assert not sent(777) or all("T02" not in (b.get("caption") or "") for b in sent(777)[1:])
        # buttons can no longer decide anything from Telegram
        bot.handle_update({"update_id": 2, "callback_query": {"id": "q", "data": f"a:{st.alerts.list()[0]['id']}:c",
                                                              "from": {"id": 501}, "message": {"chat": {"id": 501}, "message_id": 3}}})
        assert st.findings.get(fid)["decision"] is None
        # the operator rejects on the site -> the supervisor is told, again with a link only
        c.post(f"/ui/api/findings/{fid}/decision", json={"decision": "reject", "comment": "only forms on the desk"})
        assert wait(lambda: any("rejected an AI finding" in (b.get("caption") or b.get("text") or "") for b in sent(777))), calls
        notice = next(b for b in sent(777) if "rejected an AI finding" in (b.get("caption") or b.get("text") or ""))
        assert "only forms on the desk" in (notice.get("caption") or notice.get("text"))
        assert "url" in str(notice["reply_markup"]) and "callback_data" not in str(notice["reply_markup"])
        # /pending lists what waits on the site; /status answers
        bot.handle_update({"update_id": 3, "message": {"chat": {"id": 777, "type": "private"}, "text": "/pending", "from": {"id": 777}}})
        assert "Rejected by operators, not verified: 1" in sent(777)[-2]["text"]
        bot.handle_update({"update_id": 4, "message": {"chat": {"id": 501, "type": "private"}, "text": "/status", "from": {"id": 501}}})
        assert "Ждут вашего решения: 0" in sent(501)[-1]["text"]
        # jury videos never reach Telegram
        before = len([1 for m, _ in calls if m in ("sendPhoto", "sendMessage")])
        wait_done(c, upload(c, video, key="test-key").json()["job_id"])
        time.sleep(0.3)
        jury = [a for a in st.alerts.list() if (a.get("payload") or {}).get("jury")]
        assert jury and all(d["channel"] != "telegram" for a in jury for d in a["deliveries"])
        assert len([1 for m, _ in calls if m in ("sendPhoto", "sendMessage")]) == before
        # /stop unlinks
        bot.handle_update({"update_id": 5, "message": {"chat": {"id": 501, "type": "private"}, "text": "/stop", "from": {"id": 501}}})
        assert st.users.get(st.users.by_login("operator")["id"])["telegram"] is None


def _form(req, key: str):
    body = req.read().decode("utf-8", "ignore")
    import re
    m = re.search(rf'name="{key}"\r\n\r\n([^\r]+)', body)
    return m.group(1) if m else None
