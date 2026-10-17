"""Delivery channels: web (event bus), Telegram, webhook (HMAC-signed), e-mail. All optional except web."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import smtplib
import time
from email.message import EmailMessage

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
    """Alert delivery through the CashGuard bot (backend/app/telegram.py): linked users by role + optional group chats."""
    name = "telegram"

    def __init__(self, bot):
        self.bot = bot

    def target(self, role: str) -> str | None:
        return "bot" if self.bot.has_targets(role) else None

    def send(self, alert: dict, role: str, level: int) -> None:
        self.bot.send_alert(alert, role, level)


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
