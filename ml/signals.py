"""Сигналы состояния по кадрам и кандидаты событий для проверки VLM.

Идея: дешёвый детектор смотрит каждый кадр (2 fps), а дорогая VLM - только окна вокруг кандидатов.
Пороги здесь - стартовые; калибруйте их на ml/eval (docs/ml.md).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import cv2
import numpy as np

from .detector import Det
from .video import Frame

SCREEN_ON_V = float(os.getenv("SCREEN_ON_V", 140))  # средняя яркость (HSV V) верхней половины ноутбука


@dataclass
class FrameSignals:
    t: float
    people: int
    person_boxes: list[tuple[float, float, float, float]]
    groups: set[str]
    screen_v: float | None          # яркость экрана, если ноутбук найден
    person_near_laptop: bool


@dataclass
class Candidate:
    t: float
    reason: str
    priority: int                   # 3 - сильный сигнал, 0 - равномерное покрытие
    hints: list[str] = field(default_factory=list)


def _iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / area if area > 0 else 0.0


def _expand(b, k: float):
    w, h = b[2] - b[0], b[3] - b[1]
    return (b[0] - w * k, b[1] - h * k, b[2] + w * k, b[3] + h * k)


def screen_brightness(img: np.ndarray, box) -> float:
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    h, w = img.shape[:2]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return 0.0
    crop = img[y1:y1 + max(2, (y2 - y1) // 2), x1:x2]  # верхняя половина - обычно экран
    v = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2]
    return float(np.percentile(v, 75))


def compute_signals(frames: list[Frame], dets: list[list[Det]]) -> list[FrameSignals]:
    out = []
    for fr, ds in zip(frames, dets):
        persons = [d for d in ds if d.group == "person" and d.score >= 0.5]
        groups = {d.group for d in ds if d.group != "person"}
        laptops = [d for d in ds if d.group == "laptop"]
        screen_v = None
        near = False
        if laptops:
            lap = max(laptops, key=lambda d: d.score)
            screen_v = screen_brightness(fr.image, lap.box)
            near = any(_iou(_expand(lap.box, 0.6), p.box) > 0.01 for p in persons)
        out.append(FrameSignals(fr.t, len(persons), [p.box for p in persons], groups, screen_v, near))
    return out


def _smooth_counts(sig: list[FrameSignals]) -> list[int]:
    c = [s.people for s in sig]
    return [int(np.median(c[max(0, i - 1): i + 2])) for i in range(len(c))]


def find_candidates(sig: list[FrameSignals], duration: float, frame_diag: float,
                    window_sec: float, max_calls: int) -> list[Candidate]:
    cands: list[Candidate] = []
    if not sig:
        return cands
    counts = _smooth_counts(sig)

    # 1) изменение числа людей: вход/выход клиента, инкассатора, постороннего, уход кассира
    for i in range(1, len(sig)):
        if counts[i] != counts[i - 1]:
            kind = "вход" if counts[i] > counts[i - 1] else "выход"
            cands.append(Candidate(sig[i].t, f"число людей {counts[i-1]}→{counts[i]} ({kind})", 3))

    # 2) крупное перемещение человека (встал из-за стола, пошёл к двери/сейфу)
    last_t = -99.0
    for i in range(2, len(sig)):
        a, b = sig[i - 2], sig[i]
        if not a.person_boxes or not b.person_boxes:
            continue
        moved = 0.0
        for pb in b.person_boxes:
            cb = ((pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2)
            d = min(np.hypot(cb[0] - (pa[0] + pa[2]) / 2, cb[1] - (pa[1] + pa[3]) / 2) for pa in a.person_boxes)
            moved = max(moved, d / frame_diag)
        if moved > 0.08 and b.t - last_t > 3:
            cands.append(Candidate(a.t, "человек переместился", 2))
            last_t = b.t

    # 3) появление предметов: телефон, напиток/еда, сумка
    labels = {"phone": "в кадре телефон", "drink": "в кадре напиток", "food": "в кадре еда", "bag": "в кадре сумка/рюкзак"}
    for g, text in labels.items():
        present = [g in s.groups for s in sig]
        for i in range(1, len(sig) - 1):
            if present[i] and present[i + 1] and not present[i - 1]:
                cands.append(Candidate(sig[i].t, text, 3, [text]))

    # 4) экран включён, рядом с ноутбуком никого нет >= 2 с
    run_start = None
    for s in sig:
        unattended = s.screen_v is not None and s.screen_v >= SCREEN_ON_V and not s.person_near_laptop
        if unattended and run_start is None:
            run_start = s.t
        if not unattended:
            run_start = None
        if run_start is not None and s.t - run_start >= 2.0:
            cands.append(Candidate(max(0.0, run_start - 1.0), "экран включён, у ноутбука никого", 3,
                                   ["экран ноутбука включён, рядом никого"]))
            run_start = 1e9  # один кандидат на эпизод

    # 5) несколько людей у стола: периодически проверяем передачи денег/документов
    last_t = -99.0
    for s, c in zip(sig, counts):
        if c >= 2 and s.t - last_t >= window_sec:
            cands.append(Candidate(s.t, f"в кадре {c} человек", 1))
            last_t = s.t

    # 6) равномерное покрытие - ловит то, что детектор не видит (деньги, сейф, дверь)
    t = window_sec / 2
    while t < duration:
        cands.append(Candidate(t, "покрытие", 0))
        t += window_sec

    return select(cands, max_calls, min_gap=window_sec * 0.6)


def select(cands: list[Candidate], max_calls: int, min_gap: float) -> list[Candidate]:
    picked: list[Candidate] = []
    for c in sorted(cands, key=lambda c: (-c.priority, c.t)):
        close = next((p for p in picked if abs(p.t - c.t) < min_gap), None)
        if close is not None:
            close.hints.extend(h for h in c.hints if h not in close.hints)
            continue
        if len(picked) < max_calls:
            picked.append(c)
    return sorted(picked, key=lambda c: c.t)


def timeline(sig: list[FrameSignals]) -> dict:
    """Дорожки состояний для интерфейса (по одному значению на кадр выборки)."""
    return {
        "t": [round(s.t, 2) for s in sig],
        "people": [s.people for s in sig],
        "screen_on": [int(s.screen_v is not None and s.screen_v >= SCREEN_ON_V) for s in sig],
        "phone": [int("phone" in s.groups) for s in sig],
        "drink": [int("drink" in s.groups or "food" in s.groups) for s in sig],
        "bag": [int("bag" in s.groups) for s in sig],
    }


def cv_findings(sig: list[FrameSignals]) -> list[dict]:
    """Нарушения только по детектору - когда VLM недоступна (и для live-режима)."""
    found = []
    def first_run(pred, min_len=2):
        run = 0
        for s in sig:
            run = run + 1 if pred(s) else 0
            if run == min_len:
                return s.t
        return None
    t = first_run(lambda s: "phone" in s.groups)
    if t is not None:
        found.append({"code": "T15", "t": t, "confidence": 0.6, "observed": "В руках или на столе виден мобильный телефон"})
    t = first_run(lambda s: ("drink" in s.groups or "food" in s.groups) and s.people >= 1)
    if t is not None:
        found.append({"code": "T14", "t": t, "confidence": 0.55, "observed": "На рабочем месте видны напиток или еда"})
    t = first_run(lambda s: "bag" in s.groups)
    if t is not None:
        found.append({"code": "T13", "t": t, "confidence": 0.55, "observed": "На рабочем месте видна сумка или рюкзак"})
    t = first_run(lambda s: s.screen_v is not None and s.screen_v >= SCREEN_ON_V and not s.person_near_laptop, 4)
    if t is not None:
        found.append({"code": "T01", "t": max(0.0, t - 2.0), "confidence": 0.55,
                      "observed": "Экран ноутбука включён, рядом с рабочим местом никого нет"})
    return found
