"""Предметы, появившиеся на рабочем месте: где на столе что-то изменилось - без нейросети, что это - VLM на тесном кропе.

Общий скан рабочего места смотрит на весь стол сразу: пачка купюр там - 0.2% картинки, и маленькая VLM её не замечает
(Х-38: деньги прошлого клиента лежат на столе 10 с, во всех 20 замерах cash=нет). Поэтому:
  1) эталон - стол в первые секунды видео (медиана кадров, люди закрашены по рамкам детектора);
  2) каждый кадр сравниваем с эталоном по цвету (Lab: голубые купюры на бежевом столе по яркости почти не отличаются);
  3) пятно, которое лежит на одном месте несколько кадров подряд, - предмет; люди и их тени закрыты рамками;
  4) тесный кроп вокруг предмета, увеличенный, - VLM отвечает, что это (деньги, документ, карта, телефон, сумка, другое).
Ракурс и тип предмета заранее не заданы: всё от эталона того же видео и рабочего места, найденного по ноутбуку/кассиру.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

from .config import ML_DIR
from .detector import Det
from .video import Frame, to_jpeg_b64

log = logging.getLogger("ml.objects")

REF_SEC = 5.0          # эталон - медиана кадров первых секунд (люди закрашены)
COLOR_DIFF = 14.0      # порог отличия от эталона в Lab (яркость с весом 0.3 - тени и блики меньше влияют)
AREA = (2e-4, 0.05)    # площадь пятна в долях рабочего места: меньше - шум, больше - сдвинули ноутбук/стул
MIN_RUN = 3            # кадров подряд на одном месте (1.5 с при 2 кадр/с) - предмет, а не тень от руки
SAME_IOU = 0.3         # рамки в соседних кадрах с таким пересечением - тот же предмет
PERSON_PAD = 0.08      # рамку человека расширяем на эту долю - руки и тень у края рамки
CROP_SIDE = 256        # тесный кроп для VLM


@dataclass
class DeskObject:
    box: tuple[int, int, int, int]       # x1, y1, x2, y2 в пикселях кадра (по первому появлению)
    t0: float                            # появился
    t1: float                            # последний кадр, где виден
    seen: list[float] = field(default_factory=list)
    kind: str = "?"                      # cash | document | card | phone | bag | other | ?


def _iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _person_mask(ds: list[Det], roi, shape) -> np.ndarray:
    x1, y1, x2, y2 = roi
    m = np.zeros(shape[:2], bool)
    for p in ds:
        if p.group == "person" and p.score >= 0.4:
            a, b, c, d = p.box
            pw, ph = (c - a) * PERSON_PAD, (d - b) * PERSON_PAD
            m[max(0, int(b - ph)):int(d + ph), max(0, int(a - pw)):int(c + pw)] = True
    return m[y1:y2, x1:x2]


def _lab(img: np.ndarray, roi) -> np.ndarray:
    x1, y1, x2, y2 = roi
    return cv2.GaussianBlur(cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2LAB), (5, 5), 0).astype(np.float32)


def find_objects(frames: list[Frame], dets: list[list[Det]], roi) -> list[DeskObject]:
    """Предметы, которых не было на столе в первые секунды и которые потом лежат на одном месте."""
    if not frames or roi is None:
        return []
    x1, y1, x2, y2 = roi
    shape = frames[0].image.shape
    idx = [i for i, f in enumerate(frames) if f.t <= REF_SEC] or [0]
    stack = np.stack([_lab(frames[i].image, roi) for i in idx])
    hidden = np.stack([_person_mask(dets[i], roi, shape) for i in idx])
    stack[hidden] = np.nan
    with np.errstate(all="ignore"):
        ref = np.nanmedian(stack, axis=0)
    valid = ~np.isnan(ref).any(axis=2)  # пиксели, которые в эталоне всё время закрыты людьми, не сравниваем
    ref = np.nan_to_num(ref)
    roi_area = (x2 - x1) * (y2 - y1)
    w = np.array([0.3, 1.0, 1.0], np.float32)

    tracks: list[DeskObject] = []
    open_: list[tuple[DeskObject, tuple, int]] = []  # (предмет, последняя рамка, номер последнего кадра)
    for i, f in enumerate(frames):
        diff = np.sqrt(((_lab(f.image, roi) - ref) ** 2) @ w)
        m = (diff > COLOR_DIFF) & valid & ~_person_mask(dets[i], roi, shape)
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(m)
        boxes = [(x1 + bx, y1 + by, x1 + bx + bw, y1 + by + bh) for bx, by, bw, bh, area in stats[1:n]
                 if AREA[0] * roi_area <= area <= AREA[1] * roi_area]
        still = []
        for b in boxes:
            hit = next((k for k, (o, last, _) in enumerate(open_) if _iou(b, last) >= SAME_IOU), None)
            if hit is None:
                still.append((DeskObject(b, f.t, f.t, [f.t]), b, i))
            else:
                o, _, _ = open_.pop(hit)
                o.t1 = f.t
                o.seen.append(f.t)
                still.append((o, b, i))
        # предмет, который не виден в этом кадре, держим ещё 2 кадра: его могла заслонить рука
        still += [(o, last, j) for o, last, j in open_ if i - j <= 2]
        for o, _, j in open_:
            if i - j > 2 and len(o.seen) >= MIN_RUN:
                tracks.append(o)
        open_ = still
    tracks += [o for o, _, _ in open_ if len(o.seen) >= MIN_RUN]
    return sorted(tracks, key=lambda o: o.t0)


def object_crop(img: np.ndarray, box) -> np.ndarray:
    """Квадратный кроп с запасом вокруг предмета, увеличенный до CROP_SIDE: предмет занимает треть-половину кадра."""
    x1, y1, x2, y2 = box
    side = int(max(x2 - x1, y2 - y1) * 3 + 24)
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    h, w = img.shape[:2]
    a, b = max(0, cx - side // 2), max(0, cy - side // 2)
    c = img[b:min(h, b + side), a:min(w, a + side)]
    return cv2.resize(c, (CROP_SIDE, CROP_SIDE), interpolation=cv2.INTER_CUBIC)


OBJECT_PROMPT = (ML_DIR / "prompts" / "desk_object_ru.txt").read_text(encoding="utf-8")
KINDS = {"деньги": "cash", "документ": "document", "карта": "card", "телефон": "phone", "сумка": "bag",
         "ничего": "none"}


def _before(frames: list[Frame], dets: list[list[Det]], o: DeskObject) -> Frame:
    """Снимок «до»: самый ранний кадр, где место предмета не закрыто человеком, - стол, как в эталоне. Последний кадр
    перед появлением не годится: там предмет часто уже в руке у клиента (Х-38: пачка в руке на 25 с)."""
    x1, y1, x2, y2 = o.box
    for f, ds in zip(frames, dets):
        if f.t >= o.t0 - 0.5:
            break
        if not any(p.group == "person" and p.score >= 0.4 and p.box[0] < x2 and p.box[2] > x1 and p.box[1] < y2
                   and p.box[3] > y1 for p in ds):
            return f
    return frames[0]


def classify_objects(vlm, frames: list[Frame], dets: list[list[Det]], objects: list[DeskObject]) -> None:
    """VLM сравнивает место предмета «до» и «после» и называет, что появилось (change captioning): по одному кропу
    маленькая модель охотно называет деньгами что угодно (Х-4: кресло → «деньги»). Тип - большинство ответов по
    кадрам «после»: два кадра; если ответы разошлись - третий (Х-38 в зеркальном варианте: «деньги» / «документ»).
    Без большинства - «?», правила по такому предмету не срабатывают."""
    from .vlm import _extract_json

    def ask(o: DeskObject, before: str, t: float) -> str | None:
        f = min(frames, key=lambda f: abs(f.t - t))
        try:
            raw = vlm.ask(OBJECT_PROMPT, [before, to_jpeg_b64(object_crop(f.image, o.box), CROP_SIDE, 92)])
            return KINDS.get(str(_extract_json(raw).get("appeared", "")).strip().lower(), "none")
        except Exception as e:  # нет ответа - не голос
            log.warning("VLM ошибка (предмет на столе, t=%.1f): %s", t, e)
            return None

    for o in objects:
        before = to_jpeg_b64(object_crop(_before(frames, dets, o).image, o.box), CROP_SIDE, 92)
        times = list(dict.fromkeys([o.seen[min(1, len(o.seen) - 1)], o.seen[len(o.seen) // 2], o.seen[-1]]))
        answers = [a for a in (ask(o, before, t) for t in times[:2]) if a]
        if len(set(answers)) > 1 and len(times) > 2:
            answers += [a for a in [ask(o, before, times[2])] if a]
        top = max(set(answers), key=answers.count) if answers else None
        o.kind = top if top and answers.count(top) >= 2 else "?"


# кандидат для T07: держится от MIN_LIVE кадров, площадь от доли рабочего места, лежит на столе - по высоте между
# верхним краем ноутбука и нижним + DESK_BELOW его высоты (выше - стекло и люди за ним, ниже - кресло кассира);
# лежит без присмотра не меньше UNATTENDED_SEC до подхода следующего клиента (иначе его принёс новый клиент, Х-5)
MIN_LIVE, MIN_AREA_FRAC, DESK_BELOW, MAX_CANDIDATES, UNATTENDED_SEC = 6, 6e-4, 1.0, 4, 4.0


def _desk_band(dets: list[list[Det]], roi) -> tuple[float, float]:
    laps = [d.box for ds in dets for d in ds if d.group == "laptop"]
    if not laps:
        return float(roi[1]), float(roi[3])  # ноутбука нет (рабочее место по кассиру) - весь фрагмент
    y1, y2 = float(np.median([b[1] for b in laps])), float(np.median([b[3] for b in laps]))
    return y1, y2 + DESK_BELOW * (y2 - y1)


def changeover_findings(vlm, frames: list[Frame], dets: list[list[Det]], roi, states,
                        trace: list | None = None) -> list[dict]:
    """T07: при смене клиентов на столе лежит предмет, который появился, когда уходил клиент №1, и лежит до подхода
    клиента №2, - и VLM на тесном кропе дважды называет его деньгами (Х-38: пачка купюр 27–57 с, общий скан её
    не видел). Карточка/удостоверение, кресло, стекло - не деньги (Х-1, Х-4, Х-39)."""
    from .workplace import _visits
    visits = _visits(states)
    if len(visits) < 2 or roi is None:
        return []
    objs = find_objects(frames, dets, roi)
    lo, hi = _desk_band(dets, roi)
    roi_area = (roi[2] - roi[0]) * (roi[3] - roi[1])
    found = []
    for (_, b1), (a2, _) in zip(visits, visits[1:]):
        left, nxt = states[b1].t, states[a2].t
        cands = [o for o in objs if len(o.seen) >= MIN_LIVE
                 and (o.box[2] - o.box[0]) * (o.box[3] - o.box[1]) >= MIN_AREA_FRAC * roi_area
                 and lo <= (o.box[1] + o.box[3]) / 2 <= hi and left - 6 <= o.t0 <= nxt - UNATTENDED_SEC
                 and o.t1 >= nxt]
        cands = sorted(cands, key=lambda o: -len(o.seen))[:MAX_CANDIDATES]
        classify_objects(vlm, frames, dets, cands)
        if trace is not None:
            trace += [{"left": left, "next": nxt, "t0": o.t0, "t1": o.t1, "box": [int(v) for v in o.box],
                       "kind": o.kind} for o in cands]
        if any(o.kind == "cash" for o in cands):
            found.append({"code": "T07", "t": (states[a2 - 1].t + nxt) / 2, "confidence": 0.7,
                          "observed": "Предыдущий клиент ушёл, на столе осталась пачка наличных; "
                                      "к столу подходит следующий клиент"})
    return found
