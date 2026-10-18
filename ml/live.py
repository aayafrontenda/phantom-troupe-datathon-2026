from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from . import kb
from .detector import Det
from .video import Frame

log = logging.getLogger("ml.live")

ON, OFF = 3, 4
LIVE_VLM_SEC = float(os.getenv("LIVE_VLM_SEC", 4))
BACKGROUND_FRAMES = 8
DESK_WINDOW = 30
_VLM_LOCK = threading.Lock()


def _iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _grow(b, k: float):
    w, h = b[2] - b[0], b[3] - b[1]
    return b[0] - w * k, b[1] - h * k, b[2] + w * k, b[3] + h * k


@dataclass
class _State:
    on: int = 0
    off: int = 0
    active: bool = False
    since: float = 0.0


class _Desk:
    def __init__(self, jobs_busy=None):
        from .vlm import VLMClient
        self.vlm = VLMClient(timeout=20)
        self.enabled = LIVE_VLM_SEC > 0 and self.vlm.enabled
        self.jobs_busy = jobs_busy
        self.asked_frames: deque = deque(maxlen=3)
        self.t0 = time.time()
        self.laptop_dets: deque[list[Det]] = deque(maxlen=40)
        self.roi = None
        self.states: deque = deque(maxlen=DESK_WINDOW)
        self.phones: deque[float] = deque(maxlen=200)
        self.active: dict[str, dict] = {}
        self.pending: list[dict] = []
        self.last_ask = 0.0
        self.busy = False
        self.lock = threading.Lock()

    def feed(self, img: np.ndarray, dets: list[Det]) -> None:
        if not self.enabled:
            return
        now = time.time() - self.t0
        self.laptop_dets.append([d for d in dets if d.group in ("laptop", "person")])
        if self.roi is None and len(self.laptop_dets) >= 8:
            from .workplace import find_roi
            h, w = img.shape[:2]
            self.roi = find_roi(list(self.laptop_dets), w, h)
            if self.roi:
                log.info("live: рабочее место %s", self.roi)
        if self.roi is None:
            return
        from .workplace import _key, phone_times
        self.phones.extend(phone_times([Frame(t=now, index=0, image=img)], [dets], self.roi))
        changed = len(self.states) >= 2 and _key(self.states[-1]) != _key(self.states[-2])
        if self.busy or now - self.last_ask < (min(1.5, LIVE_VLM_SEC) if changed else LIVE_VLM_SEC):
            return
        try:
            if self.jobs_busy and self.jobs_busy():
                return
        except Exception:
            pass
        if not _VLM_LOCK.acquire(blocking=False):
            return
        self.busy, self.last_ask = True, now
        threading.Thread(target=self._ask, args=(Frame(t=now, index=0, image=img.copy()),), daemon=True).start()

    def _ask(self, frame: Frame) -> None:
        from .workplace import MIN_AWAY_STATES, _leave_time, _left_items, ask_state, client_findings, desk_findings
        try:
            st = ask_state(self.vlm, frame, self.roi)
            self.asked_frames.append((st.t, frame))
            with self.lock:
                self.states.append(st)
                states = list(self.states)
            found = {f["code"]: f for f in desk_findings(states, list(self.phones)) + client_findings(states)}
            n = MIN_AWAY_STATES
            if (len(states) > n and all(not s.present for s in states[-n:]) and states[-n - 1].present
                    and len(self.asked_frames) >= 2):
                answers = [_left_items(self.vlm, f, self.roi) for _, f in list(self.asked_frames)[-2:]]
                items = sorted(set.intersection(*answers))
                if items:
                    found["T02"] = {"code": "T02", "t": _leave_time(states, len(states) - n), "confidence": 0.8,
                                    "observed": "Кассир уходит с рабочего места; на столе остаются без присмотра: "
                                                + ", ".join(items)}
            with self.lock:
                for code, f in found.items():
                    if code not in self.active:
                        self.pending.append({**f, "event_ts": self.t0 + f["t"]})
                if "T02" in self.active and "T02" not in found and not states[-1].present:
                    found["T02"] = self.active["T02"]
                self.active = found
        except Exception as e:
            log.warning("live: VLM ошибка: %s", e)
        finally:
            self.busy = False
            _VLM_LOCK.release()

    def drain(self) -> list[dict]:
        with self.lock:
            out, self.pending = self.pending, []
        return out

    def active_codes(self) -> list[str]:
        with self.lock:
            return list(self.active)

    def last_state(self):
        with self.lock:
            return self.states[-1] if self.states else None


@dataclass
class LiveRules:
    states: dict[str, _State] = field(default_factory=dict)
    frames: int = 0
    background: list[tuple[str, tuple]] = field(default_factory=list)
    desk: _Desk | None = None
    busy: object = None

    def __post_init__(self):
        try:
            self.desk = _Desk(self.busy)
        except Exception as e:
            log.warning("live: скан рабочего места недоступен: %s", e)

    def _is_background(self, d: Det) -> bool:
        return any(g == d.group and _iou(b, d.box) > 0.3 for g, b in self.background)

    def _conditions(self, dets: list[Det]) -> dict[str, str]:
        persons = [d for d in dets if d.group == "person" and d.score >= 0.5]
        new = [d for d in dets if d.group in ("phone", "drink", "food", "bag") and not self._is_background(d)]
        groups = {d.group for d in new}
        cond: dict[str, str] = {}
        in_hand = [d for d in new if d.group == "phone" and any(_iou(_grow(p.box, 0.25), d.box) > 0 for p in persons)]
        if in_hand:
            cond["T15"] = "Мобильный телефон в руках у человека на рабочем месте"
        if "drink" in groups or "food" in groups:
            cond["T14"] = "На рабочем месте напиток или еда"
        if "bag" in groups:
            cond["T13"] = "На рабочем месте появилась сумка или рюкзак"
        if len(persons) > 2:
            cond["T05"] = f"В кадре {len(persons)} человека - проверьте, нет ли посторонних"
        if not persons:
            cond["EMPTY"] = "Кассир отсутствует на рабочем месте"
        return cond

    def update(self, img: np.ndarray, dets: list[Det]) -> list[dict]:
        self.frames += 1
        if self.frames <= BACKGROUND_FRAMES:
            for d in dets:
                if d.group in ("phone", "drink", "food", "bag") and not self._is_background(d):
                    self.background.append((d.group, d.box))
        cond = self._conditions(dets)
        alerts = []
        now = time.time()
        for code in set(cond) | set(self.states):
            st = self.states.setdefault(code, _State())
            if code in cond:
                st.on, st.off = st.on + 1, 0
                if st.on == 1:
                    st.since = now
                if not st.active and st.on >= ON:
                    st.active = True
                    alerts.append(self._alert(code, cond[code], event_ts=st.since))
            else:
                st.off, st.on = st.off + 1, 0
                if st.active and st.off >= OFF:
                    st.active = False
        if self.desk:
            self.desk.feed(img, dets)
            for f in self.desk.drain():
                if any(a["code"] == f["code"] for a in alerts):
                    continue
                alerts.append(self._alert(f["code"], f["observed"], f.get("confidence"), f.get("event_ts")))
        return alerts

    @staticmethod
    def _alert(code: str, message: str, confidence: float | None = None, event_ts: float | None = None) -> dict:
        now = time.time()
        event_ts = min(now, event_ts) if event_ts else now
        delay = now - event_ts
        if delay >= 1.5:
            message += f" (в {time.strftime('%H:%M:%S', time.localtime(event_ts))}, подтверждено через {delay:.0f} с)"
        a = {"code": code, "message": message, "ts": now, "event_ts": round(event_ts, 2), "delay_sec": round(delay, 1)}
        if code == "EMPTY":
            return {**a, "type": "Рабочее место пустое", "norm": None, "severity": "info"}
        a.update({"type": kb.rule_of(code)["type_name"], "norm": kb.refs_text(code), "severity": "warning"})
        if confidence is not None:
            a["confidence"] = round(float(confidence), 2)
        return a

    def active(self) -> list[str]:
        codes = [c for c, s in self.states.items() if s.active]
        if self.desk:
            codes += [c for c in self.desk.active_codes() if c not in codes]
        return codes
