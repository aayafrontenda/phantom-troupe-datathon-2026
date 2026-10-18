from __future__ import annotations

import logging

import cv2
import numpy as np

from .detector import Det
from .video import Frame

log = logging.getLogger("ml.entry")

PERSON_SCORE = 0.5
PIX_DIFF = 25
DOOR_OPEN_FRAC = 0.12
CHECK_FROM, CHECK_TO = 5.0, 12.0


def _persons(ds: list[Det], score: float = PERSON_SCORE) -> list[Det]:
    return [d for d in ds if d.group == "person" and d.score >= score]


def find_empty_room_entries(frames: list[Frame], dets: list[list[Det]], min_empty_sec: float = 1.0) -> list[tuple[int, int]]:
    counts = [len(_persons(ds)) for ds in dets]
    sm = [int(np.median(counts[max(0, i - 1): i + 2])) for i in range(len(counts))]
    out, empty_from = [], None
    for i, c in enumerate(sm):
        if c == 0:
            empty_from = i if empty_from is None else empty_from
            continue
        empty_sec = frames[i].t - frames[empty_from].t if empty_from is not None else 0.0
        if empty_from is not None and empty_sec >= min_empty_sec and (frames[empty_from].t <= 5.0 or empty_sec >= 3.0):
            out.append((i, empty_from))
        empty_from = None
    return out


def _door_roi(box, w: int, h: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    return (max(0, int(x1 - bw * 1.2)), max(0, int(y1 - bh * 0.4)), min(w, int(x2 + bw * 1.2)), min(h, int(y2 + bh * 0.2)))


def _gray(img: np.ndarray, roi) -> np.ndarray:
    x1, y1, x2, y2 = roi
    return cv2.GaussianBlur(cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY), (7, 7), 0).astype(np.float32)


def find_room_exits(frames: list[Frame], dets: list[list[Det]], min_empty_sec: float = 2.0) -> list[int]:
    counts = [len(_persons(ds)) for ds in dets]
    sm = [int(np.median(counts[max(0, i - 1): i + 2])) for i in range(len(counts))]
    out = []
    for i in range(1, len(sm)):
        if sm[i] == 0 and sm[i - 1] > 0:
            j = i
            while j < len(sm) and sm[j] == 0:
                j += 1
            if frames[j - 1].t - frames[i].t >= min_empty_sec:
                out.append(i)
    return out


def camera_moving(frames: list[Frame], t0: float, t1: float, frac: float = 0.3) -> bool:
    small = [cv2.cvtColor(cv2.resize(f.image, (48, 88), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.int16)
             for f in frames if t0 <= f.t <= t1]
    if len(small) < 2:
        return False
    changed = [float((np.abs(a - b) > PIX_DIFF).mean()) for a, b in zip(small, small[1:])]
    return sum(c > frac for c in changed) >= 3


def _door_diff(frames, dets, roi, base, t0: float, t1: float) -> list[float]:
    fracs = []
    for f, ds in zip(frames, dets):
        if not (t0 <= f.t <= t1):
            continue
        g = _gray(f.image, roi)
        mask = np.ones_like(g, dtype=bool)
        for d in _persons(ds, 0.3):
            px1, py1, px2, py2 = (int(v) for v in d.box)
            mask[max(0, py1 - roi[1]):max(0, py2 - roi[1]), max(0, px1 - roi[0]):max(0, px2 - roi[0])] = False
        if mask.sum() > 0.3 * mask.size:
            fracs.append(float((np.abs(g - base)[mask] > PIX_DIFF).mean()))
    return fracs


def door_findings(frames: list[Frame], dets: list[list[Det]]) -> list[dict]:
    found = []
    if not frames:
        return found
    h, w = frames[0].image.shape[:2]

    for i_in, i_empty in find_empty_room_entries(frames, dets):
        entrant = _persons(dets[i_in], 0.3)
        if not entrant:
            continue
        roi = _door_roi(max(entrant, key=lambda d: d.score).box, w, h)
        empty = [frames[k].image for k in range(i_empty, i_in) if frames[k].t <= frames[i_in].t - 0.5] or [frames[i_empty].image]
        base = np.mean([_gray(im, roi) for im in empty], axis=0)
        t_in = frames[i_in].t
        if camera_moving(frames, frames[i_empty].t, t_in + CHECK_TO):
            log.info("Дверь после входа в %.1f с: камера двигалась - проверка пропущена", t_in)
            continue
        fracs = _door_diff(frames, dets, roi, base, t_in + CHECK_FROM, t_in + CHECK_TO)
        if len(fracs) < 3:
            log.info("Дверь после входа в %.1f с: мало кадров для проверки", t_in)
            continue
        frac = float(np.median(fracs))
        log.info("Дверь после входа в %.1f с: отличие от закрытой %.0f%%", t_in, frac * 100)
        if frac > DOOR_OPEN_FRAC:
            found.append({"code": "T04", "t": t_in + 2.0, "confidence": min(0.9, 0.6 + frac),
                          "observed": "Сотрудник входит в помещение кассы и проходит к рабочему месту; "
                                      "дверь за собой не закрывает - участок двери не возвращается к закрытому виду",
                          "source": "detector"})

    for i_out in find_room_exits(frames, dets):
        leaver = _persons(dets[i_out - 1], 0.3)
        if not leaver:
            continue
        roi = _door_roi(max(leaver, key=lambda d: d.score).box, w, h)
        t_out = frames[i_out].t
        before = [_gray(f.image, roi) for f in frames if t_out - 12.0 <= f.t <= t_out - 4.0]
        if len(before) < 5:
            continue
        base = np.median(before, axis=0)
        if camera_moving(frames, t_out - 12.0, t_out + 10.0):
            log.info("Дверь после выхода в %.1f с: камера двигалась - проверка пропущена", t_out)
            continue
        fracs = _door_diff(frames, dets, roi, base, t_out + 3.0, t_out + 10.0)
        if len(fracs) < 3:
            log.info("Дверь после выхода в %.1f с: мало кадров для проверки", t_out)
            continue
        frac = float(np.median(fracs))
        log.info("Дверь после выхода в %.1f с: отличие от вида до ухода %.0f%%", t_out, frac * 100)
        if frac > DOOR_OPEN_FRAC:
            found.append({"code": "T04", "t": t_out, "confidence": min(0.9, 0.6 + frac),
                          "observed": "Сотрудник выходит из помещения кассы, касса остаётся пустой; "
                                      "дверь за собой не закрывает - участок двери не возвращается к виду до ухода",
                          "source": "detector"})
    return found
