"""Alert policy engine: severity, dedup/cooldown, routing by role, timed escalation, acknowledgement."""
from __future__ import annotations

import concurrent.futures as cf
import logging
import threading
import time
from typing import Any

import yaml

from .. import metrics
from ..config import Settings, get_settings
from ..db import Database, loads
from ..events import EventBus
from .channels import Channel, EmailChannel, LogChannel, TelegramChannel, WebChannel, WebhookChannel

log = logging.getLogger("backend.alerts")

STATES = {"open", "acknowledged", "resolved", "false_positive"}
DEFAULT_POLICY: dict[str, Any] = {
    "defaults": {"severity": "medium", "dedup_window_sec": 300, "cooldown_sec": 60},
    "severity_by_type": {},
    "routing": {"critical": {"notify": ["operator", "supervisor"], "escalate_after_sec": 120},
                "high": {"notify": ["operator"], "escalate_to": "supervisor", "escalate_after_sec": 300},
                "medium": {"notify": ["operator"], "escalate_to": "supervisor", "escalate_after_sec": 900},
                "low": {"notify": ["operator"], "escalate_after_sec": 0},
                "info": {"notify": [], "escalate_after_sec": 0}},
    "channels": {"operator": ["web", "telegram"], "supervisor": ["web", "telegram", "email", "webhook"],
                 "admin": ["web", "telegram"]},
}


def load_policy(path) -> dict:
    policy = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_POLICY.items()}
    try:
        with open(path, encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(policy.get(k), dict):
                policy[k].update(v)
            else:
                policy[k] = v
    except FileNotFoundError:
        log.warning("alerts policy %s not found, using defaults", path)
    return policy


class AlertEngine:
    def __init__(self, db: Database, bus: EventBus, settings: Settings | None = None, channels: list[Channel] | None = None):
        self.db = db
        self.bus = bus
        self.s = settings or get_settings()
        self.policy = load_policy(self.s.alerts_config)
        from ..telegram import TelegramBot
        self.telegram = TelegramBot(self.s)
        self.channels: dict[str, Channel] = {c.name: c for c in (channels or [
            WebChannel(bus), TelegramChannel(self.telegram), WebhookChannel(self.s), EmailChannel(self.s), LogChannel()])}
        self._pool = cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="alert-delivery")
        self._stop = threading.Event()
        self._esc = threading.Thread(target=self._escalation_loop, name="alert-escalation", daemon=True)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._esc.start()
        self.telegram.start()

    def stop(self) -> None:
        self._stop.set()
        self.telegram.stop()
        self._pool.shutdown(wait=True, cancel_futures=True)
        if self._esc.is_alive() and self._esc is not threading.current_thread():
            self._esc.join(3)

    # ------------------------------------------------------------------ policy helpers
    def severity_of(self, type_code: str | None) -> str:
        return self.policy["severity_by_type"].get(type_code or "", self.policy["defaults"].get("severity", "medium"))

    def _routing(self, severity: str) -> dict:
        return self.policy["routing"].get(severity, self.policy["routing"]["medium"])

    def _channels_for(self, role: str) -> list[Channel]:
        names = self.policy["channels"].get(role, ["web"])
        out = [self.channels[n] for n in names if n in self.channels]
        if "log" in self.channels and self.channels["log"] not in out:
            out.append(self.channels["log"])
        return out

    # ------------------------------------------------------------------ create
    def handle(self, event: dict, actor: str = "system") -> dict | None:
        """event: {source, job_id?, camera_id?, camera_name?, type_code, type_name, t_sec?, confidence?, message,
        norm?, evidence_b64?, link?, filename?}. Returns the alert (new or updated) or None if muted by cooldown."""
        now = time.time()
        code = event.get("type_code") or "T99"
        severity = event.get("severity") or self.severity_of(code)
        scope = event.get("camera_id") or event.get("job_id") or "global"
        dedup_key = f"{scope}:{code}"
        dedup_window = float(self.policy["defaults"].get("dedup_window_sec", 300))
        cooldown = float(self.policy["defaults"].get("cooldown_sec", 60))
        with self._lock:
            ev_id = self.db.insert("events", {
                "job_id": event.get("job_id"), "camera_id": event.get("camera_id"), "type_code": code,
                "type_name": event.get("type_name"), "t_sec": event.get("t_sec"), "confidence": event.get("confidence"),
                "source": event.get("source"), "payload": {k: v for k, v in event.items() if k != "evidence_b64"},
                "created_at": now})
            existing = self.db.one("SELECT * FROM alerts WHERE dedup_key=? AND state='open' AND created_at > ? "
                                   "ORDER BY created_at DESC LIMIT 1", (dedup_key, now - dedup_window))
            if existing is not None:
                if now - existing["updated_at"] < cooldown:
                    self.db.update("alerts", "id", existing["id"], {"count": existing["count"] + 1, "updated_at": now})
                    return None
                self.db.update("alerts", "id", existing["id"], {"count": existing["count"] + 1, "updated_at": now,
                                                                "message": event.get("message") or existing["message"]})
                alert = self.get(existing["id"])
                self.bus.publish("alerts", {"type": "alert_update", "alert": alert})
                alert["new"] = False
                return alert
            routing = self._routing(severity)
            esc_after = float(routing.get("escalate_after_sec") or 0)
            row = {
                "event_id": ev_id, "job_id": event.get("job_id"), "camera_id": event.get("camera_id"),
                "type_code": code, "type_name": event.get("type_name"), "severity": severity, "state": "open",
                "message": event.get("message"), "dedup_key": dedup_key, "count": 1, "escalation_level": 0,
                "escalate_at": (now + esc_after) if esc_after > 0 else None,
                "payload": {k: v for k, v in event.items() if k not in ("evidence_b64",)},
                "created_at": now, "updated_at": now,
            }
            aid = self.db.insert("alerts", row)
        alert = self.get(aid)
        alert["evidence_b64"] = event.get("evidence_b64")
        metrics.ALERTS_TOTAL.labels(severity, event.get("source") or "unknown").inc()
        log.info("alert #%d %s %s (%s) scope=%s", aid, severity, code, event.get("type_name"), scope)
        for role in routing.get("notify", []):
            self._deliver(alert, role, 0)
        self.db.audit("alert.create", actor, str(aid), {"severity": severity, "type_code": code, "scope": scope})
        return {**{k: v for k, v in alert.items() if k != "evidence_b64"}, "new": True}

    # ------------------------------------------------------------------ delivery
    def _deliver(self, alert: dict, role: str, level: int) -> None:
        jury = bool((alert.get("payload") or {}).get("jury"))
        for ch in self._channels_for(role):
            if jury and ch.name not in ("web", "log"):   # jury test videos never leave the server (brief, section 10)
                continue
            target = ch.target(role)
            did = self.db.insert("alert_deliveries", {"alert_id": alert["id"], "channel": ch.name, "target": target,
                                                      "status": "pending" if target else "skipped", "attempts": 0,
                                                      "created_at": time.time(), "updated_at": time.time()})
            if not target:
                continue
            try:
                self._pool.submit(self._send_with_retry, ch, dict(alert), role, level, did)
            except RuntimeError:  # shutting down
                self.db.update("alert_deliveries", "id", did, {"status": "skipped", "last_error": "service stopping"})

    def _send_with_retry(self, ch: Channel, alert: dict, role: str, level: int, did: int) -> None:
        delays = (0, 2, 5)
        err = ""
        for attempt, delay in enumerate(delays, start=1):
            if delay:
                time.sleep(delay)
            try:
                ch.send(alert, role, level)
                self.db.update("alert_deliveries", "id", did, {"status": "sent", "attempts": attempt, "updated_at": time.time()})
                metrics.ALERT_DELIVERIES.labels(ch.name, "sent").inc()
                return
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:300]
                log.warning("alert #%s via %s -> %s failed (attempt %d): %s", alert.get("id"), ch.name, role, attempt, err)
        self.db.update("alert_deliveries", "id", did, {"status": "failed", "attempts": len(delays), "last_error": err,
                                                       "updated_at": time.time()})
        metrics.ALERT_DELIVERIES.labels(ch.name, "failed").inc()

    # ------------------------------------------------------------------ escalation
    def _escalation_loop(self) -> None:
        while not self._stop.wait(5):
            try:
                self.escalate_due()
            except Exception:
                log.exception("escalation pass failed")

    def escalate_due(self, now: float | None = None) -> int:
        now = now or time.time()
        due = self.db.all("SELECT * FROM alerts WHERE state='open' AND escalate_at IS NOT NULL AND escalate_at <= ?", (now,))
        n = 0
        for a in due:
            routing = self._routing(a["severity"])
            level = int(a["escalation_level"]) + 1
            role = routing.get("escalate_to") or "supervisor"
            esc_after = float(routing.get("escalate_after_sec") or 0)
            next_at = (now + esc_after * 2) if (esc_after > 0 and level < 2) else None
            self.db.update("alerts", "id", a["id"], {"escalation_level": level, "escalate_at": next_at, "updated_at": now})
            alert = self.get(a["id"])
            log.warning("alert #%d escalated to level %d (%s)", a["id"], level, role)
            self._deliver(alert, role, level)
            if level >= 2 and "admin" in self.policy["channels"]:
                self._deliver(alert, "admin", level)
            self.bus.publish("alerts", {"type": "alert_escalated", "alert": alert, "level": level})
            self.db.audit("alert.escalate", "system", str(a["id"]), {"level": level, "role": role})
            n += 1
        return n

    # ------------------------------------------------------------------ ack / read
    def ack(self, alert_id: int, by: str, decision: str = "acknowledged", comment: str | None = None,
            record_feedback: bool = True) -> dict | None:
        if decision not in STATES or decision == "open":
            raise ValueError(f"bad decision {decision!r}")
        a = self.get(alert_id)
        if a is None:
            return None
        now = time.time()
        self.db.update("alerts", "id", alert_id, {"state": decision, "acked_by": by, "acked_at": now,
                                                  "escalate_at": None, "updated_at": now})
        if decision == "false_positive" and record_feedback:
            self.db.insert("feedback", {"job_id": a.get("job_id"), "violation_index": None, "decision": "reject",
                                        "comment": f"[alert #{alert_id} false positive by {by}] {comment or ''}".strip(),
                                        "type_code": a.get("type_code"), "timecode_sec": (a.get("payload") or {}).get("t_sec"),
                                        "filename": (a.get("payload") or {}).get("filename"), "created_at": now})
        self.db.audit("alert.ack", by, str(alert_id), {"decision": decision, "comment": comment})
        alert = self.get(alert_id)
        self.bus.publish("alerts", {"type": "alert_update", "alert": alert})
        return alert

    def reopen(self, alert_id: int) -> dict | None:
        if self.get(alert_id) is None:
            return None
        self.db.update("alerts", "id", alert_id, {"state": "open", "acked_by": None, "acked_at": None, "updated_at": time.time()})
        alert = self.get(alert_id)
        self.bus.publish("alerts", {"type": "alert_update", "alert": alert})
        return alert

    def sync_review(self, job_id: str, type_code: str | None, t_sec: float | None, decision: str, by: str) -> None:
        """A reviewer decision on a check finding closes (or reopens) the alert raised for it."""
        rows = self.db.all("SELECT id, payload FROM alerts WHERE job_id=? AND type_code=?", (job_id, type_code or "T99"))
        for r in rows:
            t = (loads(r["payload"], {}) or {}).get("t_sec")
            if t_sec is not None and t is not None and abs(float(t) - float(t_sec)) > 0.6:
                continue
            if decision == "clear":
                self.db.update("alerts", "id", r["id"], {"state": "open", "acked_by": None, "acked_at": None,
                                                         "updated_at": time.time()})
                self.bus.publish("alerts", {"type": "alert_update", "alert": self.get(r["id"])})
            else:
                self.ack(r["id"], by=by, decision="resolved" if decision == "confirm" else "false_positive",
                         comment="decision made on the check page", record_feedback=False)

    def get(self, alert_id: int) -> dict | None:
        a = self.db.one("SELECT * FROM alerts WHERE id=?", (alert_id,))
        if a is None:
            return None
        a["payload"] = loads(a.get("payload"), {})
        for k in ("camera_name", "filename", "link", "norm", "t_sec", "confidence", "source"):
            if k in a["payload"] and k not in a:
                a[k] = a["payload"][k]
        a["deliveries"] = self.db.all("SELECT channel, target, status, attempts, last_error FROM alert_deliveries "
                                      "WHERE alert_id=? ORDER BY id", (alert_id,))
        f = self.db.one("SELECT id FROM findings WHERE alert_id=?", (alert_id,))
        if f is None and a.get("job_id") is not None:
            t = a["payload"].get("t_sec")
            f = self.db.one("SELECT id FROM findings WHERE job_id=? AND type_code=? AND (? IS NULL OR ABS(t_sec-?)<0.6) LIMIT 1",
                            (a["job_id"], a.get("type_code"), t, t))
        a["finding_id"] = f["id"] if f else None
        return a

    def list(self, state: str | None = None, limit: int = 100, camera_id: str | None = None,
             camera_ids: list[str] | None = None) -> list[dict]:
        sql, params = "SELECT id FROM alerts", []
        conds = []
        if state:
            conds.append("state=?")
            params.append(state)
        if camera_id:
            conds.append("camera_id=?")
            params.append(camera_id)
        if camera_ids is not None:
            marks = ",".join("?" for _ in camera_ids) or "''"
            conds.append(f"(camera_id IS NULL OR camera_id IN ({marks}))")
            params.extend(camera_ids)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [self.get(r["id"]) for r in self.db.all(sql, params)]

    def summary(self) -> dict:
        rows = self.db.all("SELECT severity, state, COUNT(*) AS n FROM alerts GROUP BY severity, state")
        out: dict[str, Any] = {"open": 0, "by_severity": {}, "by_state": {}}
        for r in rows:
            out["by_severity"][r["severity"]] = out["by_severity"].get(r["severity"], 0) + r["n"]
            out["by_state"][r["state"]] = out["by_state"].get(r["state"], 0) + r["n"]
            if r["state"] == "open":
                out["open"] += r["n"]
        mtta = self.db.one("SELECT AVG(acked_at - created_at) AS v FROM alerts WHERE acked_at IS NOT NULL") or {}
        out["mtta_sec"] = round(mtta.get("v") or 0.0, 1)
        return out
