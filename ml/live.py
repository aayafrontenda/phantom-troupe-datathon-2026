"""Правила live-режима (поток с камеры).

Два слоя:
  1) детектор на каждом кадре (2–4 кадра/с) — быстрые тревоги: телефон, напиток, новая сумка, люди;
     предметы, стоявшие на месте с первых кадров (счётная машина = «чемодан», бутылка на столе), — обстановка;
  2) раз в LIVE_VLM_SEC секунд в фоне — тот же скан рабочего места, что и для видео (ml/workplace.py):
     увеличенный фрагмент вокруг ноутбука → вопросы о фактах → те же правила T01/T02/T03/T14/T15.
     Один вызов VLM на процесс одновременно — задачи жюри на той же видеокарте важнее.

Алерт детектора срабатывает, когда условие держится >= ON кадров подряд, и снимается после OFF кадров без него.
"""
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
LIVE_VLM_SEC = float(os.getenv("LIVE_VLM_SEC", 4))  # 0 — live без VLM, только детектор
BACKGROUND_FRAMES = 8      # предметы с первых кадров сессии — обстановка, не тревога
DESK_WINDOW = 30           # сколько последних состояний рабочего места держим (≈ 2 мин при 4 с)
_VLM_LOCK = threading.Lock()  # один вызов VLM из live на процесс


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
    since: float = 0.0  # время первого кадра, на котором условие появилось, — момент нарушения


class _Desk:
    """Скан рабочего места в фоне: дорожка состояний и нарушения по тем же правилам, что для видео."""

    def __init__(self):
        from .vlm import VLMClient
        self.vlm = VLMClient()
        self.enabled = LIVE_VLM_SEC > 0 and self.vlm.enabled
        self.t0 = time.time()
        self.laptop_dets: deque[list[Det]] = deque(maxlen=40)
        self.roi = None
        self.states: deque = deque(maxlen=DESK_WINDOW)
        self.phones: deque[float] = deque(maxlen=200)
        self.active: dict[str, dict] = {}     # код -> находка, пока она держится в окне
        self.pending: list[dict] = []          # новые тревоги для следующего update()
        self.last_ask = 0.0
        self.busy = False
        self.lock = threading.Lock()

    def feed(self, img: np.ndarray, dets: list[Det]) -> None:
        if not self.enabled:
            return
        now = time.time() - self.t0
        self.laptop_dets.append([d for d in dets if d.group in ("laptop", "person")])
        if self.roi is None and len(self.laptop_dets) >= 8:
            # по ноутбуку, а без него — по месту, где дольше всех сидит человек (как для видео)
            from .workplace import find_roi
            h, w = img.shape[:2]
            self.roi = find_roi(list(self.laptop_dets), w, h)
            if self.roi:
                log.info("live: рабочее место %s", self.roi)
        if self.roi is None:
            return
        x1, y1, x2, y2 = self.roi
        if any(d.group == "phone" and x1 <= d.center[0] <= x2 and y1 <= d.center[1] <= y2 for d in dets):
            self.phones.append(now)
        # состояние только что изменилось (встала, ушла, открыла сейф) — подтверждаем быстрее, иначе раз в LIVE_VLM_SEC
        from .workplace import _key
        changed = len(self.states) >= 2 and _key(self.states[-1]) != _key(self.states[-2])
        if self.busy or now - self.last_ask < (min(1.5, LIVE_VLM_SEC) if changed else LIVE_VLM_SEC):
            return
        if not _VLM_LOCK.acquire(blocking=False):
            return  # VLM занята другой камерой — спросим на следующем кадре
        self.busy, self.last_ask = True, now
        threading.Thread(target=self._ask, args=(Frame(t=now, index=0, image=img.copy()),), daemon=True).start()

    def _ask(self, frame: Frame) -> None:
        from .workplace import ask_state, desk_findings
        try:
            st = ask_state(self.vlm, frame, self.roi)
            with self.lock:
                self.states.append(st)
                found = {f["code"]: f for f in desk_findings(list(self.states), list(self.phones))}
                for code, f in found.items():
                    if code not in self.active:
                        # t находки — секунды от начала сессии: момент самого нарушения (встала и ушла), а не ответа VLM
                        self.pending.append({**f, "event_ts": self.t0 + f["t"]})
                self.active = found
        except Exception as e:  # VLM недоступна — live продолжает работать на детекторе
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
        """Последний ответ VLM о рабочем месте (для окна live_cam) или None."""
        with self.lock:
            return self.states[-1] if self.states else None


@dataclass
class LiveRules:
    states: dict[str, _State] = field(default_factory=dict)
    frames: int = 0
    background: list[tuple[str, tuple]] = field(default_factory=list)  # (группа, рамка) обстановки
    desk: _Desk | None = None

    def __post_init__(self):
        try:
            self.desk = _Desk()
        except Exception as e:
            log.warning("live: скан рабочего места недоступен: %s", e)

    def _is_background(self, d: Det) -> bool:
        return any(g == d.group and _iou(b, d.box) > 0.3 for g, b in self.background)

    def _conditions(self, dets: list[Det]) -> dict[str, str]:
        persons = [d for d in dets if d.group == "person" and d.score >= 0.5]
        new = [d for d in dets if d.group in ("phone", "drink", "food", "bag") and not self._is_background(d)]
        groups = {d.group for d in new}
        cond: dict[str, str] = {}
        # телефон — только в руке (рядом с человеком): мышь/пульт на пустом столе детектор тоже зовёт «cell phone»
        in_hand = [d for d in new if d.group == "phone" and any(_iou(_grow(p.box, 0.25), d.box) > 0 for p in persons)]
        if in_hand:
            cond["T15"] = "Мобильный телефон в руках у человека на рабочем месте"
        if "drink" in groups or "food" in groups:
            cond["T14"] = "На рабочем месте напиток или еда"
        if "bag" in groups:
            cond["T13"] = "На рабочем месте появилась сумка или рюкзак"
        if len(persons) > 2:
            cond["T05"] = f"В кадре {len(persons)} человека — проверьте, нет ли посторонних"
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
        """Тревога. ts — когда подтверждена; event_ts — когда нарушение произошло; delay_sec — разница."""
        now = time.time()
        event_ts = min(now, event_ts) if event_ts else now
        delay = now - event_ts
        if delay >= 1.5:  # видно в интерфейсе без правок фронта: когда случилось и через сколько подтверждено
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
