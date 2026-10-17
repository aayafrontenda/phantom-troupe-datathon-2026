"""Delivery channels: web (event bus), Telegram, webhook (HMAC-signed), e-mail. All optional except web."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import smtplib
import threading
import time
from email.message import EmailMessage
from typing import Callable

import httpx

from ..config import Settings
from ..events import EventBus

log = logging.getLogger("backend.alerts.channels")


class Channel:
    name = "base"

    def target(self, role: str) -> str | None:  # None = channel not configured for this role
        return None

    def send(self, alert: dict, role: str, level: int) -> None:
        raise NotImplementedError


def _text(alert: dict, level: int, public_url: str) -> str:
    where = alert.get("camera_name") or alert.get("camera_id") or (f"видео {alert.get('filename')}" if alert.get("filename") else "")
    t = alert.get("t_sec")
    tc = f" @ {int(t // 60):02d}:{t % 60:04.1f}" if isinstance(t, (int, float)) else ""
    head = "ЭСКАЛАЦИЯ " if level > 0 else ""
    sev = {"critical": "КРИТИЧНО", "high": "ВЫСОКАЯ", "medium": "СРЕДНЯЯ", "low": "НИЗКАЯ", "info": "ИНФО"}.get(
        alert.get("severity", ""), alert.get("severity", ""))
    lines = [f"{head}[{sev}] {alert.get('type_name') or alert.get('type_code')}",
             f"Где: {where}{tc}" if where else "",
             alert.get("message") or ""]
    if alert.get("norm"):
        lines.append(f"Норма: {alert['norm']}")
    if alert.get("count", 1) > 1:
        lines.append(f"Повторов: {alert['count']}")
    link = alert.get("link") or ""
    if public_url and link:
        lines.append(f"{public_url.rstrip('/')}{link}")
    return "\n".join(x for x in lines if x)


class WebChannel(Channel):
    name = "web"

    def __init__(self, bus: EventBus):
        self.bus = bus

    def target(self, role: str) -> str | None:
        return "ui"

    def send(self, alert: dict, role: str, level: int) -> None:
        self.bus.publish("alerts", {"type": "alert", "role": role, "level": level,
                                    "alert": {k: v for k, v in alert.items() if k != "evidence_b64"}})


class TelegramChannel(Channel):
    name = "telegram"

    def __init__(self, settings: Settings, on_callback: Callable[[int, str, str], None] | None = None):
        self.token = settings.telegram_bot_token
        self.chats = {"operator": settings.telegram_chat_operator, "supervisor": settings.telegram_chat_supervisor,
                      "admin": settings.telegram_chat_supervisor or settings.telegram_chat_operator}
        self.public_url = settings.public_url
        self.api = f"https://api.telegram.org/bot{self.token}"
        self.on_callback = on_callback
        self.transport: httpx.BaseTransport | None = None   # test hook
        self._stop = threading.Event()
        self._poller: threading.Thread | None = None

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(timeout=timeout, transport=self.transport)

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def target(self, role: str) -> str | None:
        return self.chats.get(role) or None if self.enabled else None

    def send(self, alert: dict, role: str, level: int) -> None:
        chat = self.target(role)
        if not chat:
            return
        text = _text(alert, level, self.public_url)
        keyboard = {"inline_keyboard": [[{"text": "Принял", "callback_data": f"ack:{alert['id']}"},
                                         {"text": "Ложное", "callback_data": f"fp:{alert['id']}"}]]}
        with self._client(20) as c:
            if alert.get("evidence_b64"):
                r = c.post(f"{self.api}/sendPhoto", data={"chat_id": chat, "caption": text[:1000],
                                                          "reply_markup": json.dumps(keyboard)},
                           files={"photo": ("evidence.jpg", base64.b64decode(alert["evidence_b64"]), "image/jpeg")})
            else:
                r = c.post(f"{self.api}/sendMessage", json={"chat_id": chat, "text": text[:4000],
                                                            "reply_markup": keyboard})
            r.raise_for_status()
            if not r.json().get("ok"):
                raise RuntimeError(f"telegram: {r.text[:200]}")

    # --- inline buttons -> ack ----------------------------------------------------
    def start_poller(self) -> None:
        if not self.enabled or self.on_callback is None:
            return
        self._poller = threading.Thread(target=self._poll, name="telegram-poller", daemon=True)
        self._poller.start()

    def stop(self) -> None:
        self._stop.set()
        if self._poller is not None and self._poller is not threading.current_thread():
            self._poller.join(3)

    def _poll(self) -> None:
        offset = 0
        while not self._stop.is_set():
            try:
                with self._client(40) as c:
                    r = c.get(f"{self.api}/getUpdates", params={"timeout": 25, "offset": offset,
                                                                "allowed_updates": json.dumps(["callback_query"])})
                    for upd in r.json().get("result", []):
                        offset = upd["update_id"] + 1
                        cq = upd.get("callback_query")
                        if not cq:
                            continue
                        data = cq.get("data", "")
                        action, _, aid = data.partition(":")
                        who = (cq.get("from") or {}).get("username") or str((cq.get("from") or {}).get("id"))
                        if action in ("ack", "fp") and aid.isdigit():
                            decision = "acknowledged" if action == "ack" else "false_positive"
                            try:
                                self.on_callback(int(aid), f"tg:{who}", decision)
                                c.post(f"{self.api}/answerCallbackQuery",
                                       json={"callback_query_id": cq["id"], "text": "Принято" if action == "ack" else "Отмечено как ложное"})
                                msg = cq.get("message") or {}
                                if msg:
                                    c.post(f"{self.api}/editMessageReplyMarkup",
                                           json={"chat_id": msg["chat"]["id"], "message_id": msg["message_id"],
                                                 "reply_markup": {"inline_keyboard": []}})
                            except Exception:
                                log.exception("telegram callback failed")
            except Exception as e:
                log.warning("telegram poll error: %s", e)
                time.sleep(5)


class WebhookChannel(Channel):
    name = "webhook"

    def __init__(self, settings: Settings):
        self.url = settings.alert_webhook_url
        self.secret = settings.alert_webhook_secret.encode("utf-8")
        self.post = None  # test hook

    def target(self, role: str) -> str | None:
        return self.url or None

    def send(self, alert: dict, role: str, level: int) -> None:
        if not self.url:
            return
        body = json.dumps({"event": "alert", "role": role, "level": level, "ts": time.time(),
                           "alert": {k: v for k, v in alert.items() if k != "evidence_b64"}}, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["X-Signature"] = "sha256=" + hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        if self.post is not None:
            self.post(self.url, body, headers)
            return
        with httpx.Client(timeout=15) as c:
            r = c.post(self.url, content=body, headers=headers)
            r.raise_for_status()


class EmailChannel(Channel):
    name = "email"

    def __init__(self, settings: Settings):
        self.s = settings
        self.targets = {"operator": settings.alert_email_operator, "supervisor": settings.alert_email_supervisor,
                        "admin": settings.alert_email_supervisor}

    def target(self, role: str) -> str | None:
        return self.targets.get(role) or None if self.s.smtp_host else None

    def send(self, alert: dict, role: str, level: int) -> None:
        to = self.target(role)
        if not to:
            return
        msg = EmailMessage()
        msg["Subject"] = f"[CashGuard {alert.get('severity', '').upper()}] {alert.get('type_name') or alert.get('type_code')}"
        msg["From"] = self.s.smtp_from or self.s.smtp_user
        msg["To"] = to
        msg.set_content(_text(alert, level, self.s.public_url))
        if alert.get("evidence_b64"):
            msg.add_attachment(base64.b64decode(alert["evidence_b64"]), maintype="image", subtype="jpeg",
                               filename="evidence.jpg")
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=20) as srv:
            srv.ehlo()
            try:
                srv.starttls()
            except smtplib.SMTPException:
                pass
            if self.s.smtp_user:
                srv.login(self.s.smtp_user, self.s.smtp_password)
            srv.send_message(msg)


class LogChannel(Channel):
    """Always-on fallback used in tests and when nothing else is configured."""
    name = "log"

    def target(self, role: str) -> str | None:
        return "log"

    def send(self, alert: dict, role: str, level: int) -> None:
        log.info("alert #%s -> %s (level %d): [%s] %s", alert.get("id"), role, level, alert.get("severity"),
                 alert.get("type_name") or alert.get("type_code"))
