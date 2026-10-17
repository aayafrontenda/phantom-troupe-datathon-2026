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


def test_telegram_channel_requests(tmp_path):
    import httpx
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path.endswith("/getUpdates"):
            return httpx.Response(200, json={"ok": True, "result": [
                {"update_id": 1, "callback_query": {"id": "cq1", "data": "fp:1", "from": {"username": "boss"},
                                                     "message": {"chat": {"id": 5}, "message_id": 7}}}]})
        return httpx.Response(200, json={"ok": True, "result": {}})

    with make_app(tmp_path, TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_CHAT_OPERATOR="111",
                  TELEGRAM_CHAT_SUPERVISOR="222") as (c, st):
        tg = st.alerts.telegram
        tg.transport = httpx.MockTransport(handler)
        a = st.alerts.handle(_event(evidence_b64=base64.b64encode(_jpeg(1)).decode()))
        for _ in range(60):
            if len([x for x in calls if x.url.path.endswith("/sendPhoto")]) >= 2:
                break
            time.sleep(0.05)
        photo_calls = [x for x in calls if x.url.path.endswith("/sendPhoto")]
        assert len(photo_calls) == 2, [x.url.path for x in calls]       # critical -> operator + supervisor
        assert {"111", "222"} <= {x.url.params.get("chat_id") or _form(x, "chat_id") for x in photo_calls}
        d = [x for x in st.alerts.get(a["id"])["deliveries"] if x["channel"] == "telegram"]
        for _ in range(40):
            if all(x["status"] == "sent" for x in d):
                break
            time.sleep(0.05)
            d = [x for x in st.alerts.get(a["id"])["deliveries"] if x["channel"] == "telegram"]
        assert all(x["status"] == "sent" for x in d)
        # one poll iteration handles the inline button -> alert marked false positive
        tg._stop.set()
        tg._stop.clear()
        import threading
        t = threading.Thread(target=tg._poll, daemon=True)
        t.start()
        for _ in range(60):
            if st.alerts.get(a["id"])["state"] == "false_positive":
                break
            time.sleep(0.05)
        tg._stop.set()
        t.join(5)
        assert st.alerts.get(a["id"])["state"] == "false_positive"
        assert any(x.url.path.endswith("/answerCallbackQuery") for x in calls)


def _form(req, key: str):
    body = req.read().decode("utf-8", "ignore")
    import re
    m = re.search(rf'name="{key}"\r\n\r\n([^\r]+)', body)
    return m.group(1) if m else None
