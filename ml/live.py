"""Правила live-режима (поток с камеры): только детектор, без VLM — чтобы держать 2–4 кадра/с.

Алерт срабатывает, когда условие держится >= ON кадров подряд, и снимается после OFF кадров без него.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from . import kb
from .detector import Det
from .signals import SCREEN_ON_V, _expand, _iou, screen_brightness

ON, OFF = 3, 4


@dataclass
class _State:
    on: int = 0
    off: int = 0
    active: bool = False


@dataclass
class LiveRules:
    states: dict[str, _State] = field(default_factory=dict)

    def _conditions(self, img: np.ndarray, dets: list[Det]) -> dict[str, str]:
        persons = [d for d in dets if d.group == "person" and d.score >= 0.5]
        groups = {d.group for d in dets}
        cond: dict[str, str] = {}
        if "phone" in groups:
            cond["T15"] = "В кадре мобильный телефон"
        if "drink" in groups or "food" in groups:
            cond["T14"] = "На рабочем месте напиток или еда"
        if "bag" in groups:
            cond["T13"] = "На рабочем месте сумка или рюкзак"
        if len(persons) > 2:
            cond["T05"] = f"В кадре {len(persons)} человека — проверьте, нет ли посторонних"
        laptops = [d for d in dets if d.group == "laptop"]
        if laptops:
            lap = max(laptops, key=lambda d: d.score)
            near = any(_iou(_expand(lap.box, 0.6), p.box) > 0.01 for p in persons)
            if not near and screen_brightness(img, lap.box) >= SCREEN_ON_V:
                cond["T01"] = "Экран включён, у рабочего места никого"
        if not persons:
            cond["EMPTY"] = "Кассир отсутствует на рабочем месте"
        return cond

    def update(self, img: np.ndarray, dets: list[Det]) -> list[dict]:
        cond = self._conditions(img, dets)
        alerts = []
        for code in set(cond) | set(self.states):
            st = self.states.setdefault(code, _State())
            if code in cond:
                st.on, st.off = st.on + 1, 0
                if not st.active and st.on >= ON:
                    st.active = True
                    alerts.append(self._alert(code, cond[code]))
            else:
                st.off, st.on = st.off + 1, 0
                if st.active and st.off >= OFF:
                    st.active = False
        return alerts

    @staticmethod
    def _alert(code: str, message: str) -> dict:
        if code == "EMPTY":
            return {"code": code, "type": "Рабочее место пустое", "message": message, "norm": None,
                    "severity": "info", "ts": time.time()}
        return {"code": code, "type": kb.rule_of(code)["type_name"], "message": message,
                "norm": kb.refs_text(code), "severity": "warning", "ts": time.time()}

    def active(self) -> list[str]:
        return [c for c, s in self.states.items() if s.active]
