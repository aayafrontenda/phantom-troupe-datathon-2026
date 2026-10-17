"""Рабочее место кассира: где оно на кадре и что на нём происходит.

Ноутбук детектор находит на всех ракурсах — вокруг него вырезаем фрагмент стола, увеличиваем и
задаём VLM простые вопросы о состоянии (кто за столом, что на экране, деньги, сумка, сейф).
Нарушения T01–T03 выводят правила по дорожке состояний, а не VLM: вопрос «найди нарушение»
маленькая модель отвечает выдумками, а вопрос о факте на увеличенном фрагменте — почти без ошибок.
Ручных зон нет — всё от положения ноутбука, поэтому новый ракурс не ломает логику.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace

import cv2
import numpy as np

from .config import ML_DIR
from .detector import Det
from .video import Frame, to_jpeg_b64
from .vlm import VLMClient, _extract_json

log = logging.getLogger("ml.workplace")

PROMPT = (ML_DIR / "prompts" / "workplace_ru.txt").read_text(encoding="utf-8")

# расширение рамки ноутбука (в его ширинах/высотах): влево, вверх, вправо, вниз — захватываем стол и сейф рядом
ROI_EXPAND = (1.2, 1.2, 1.2, 1.5)
CROP_SIDE = 448
# повтор прошлого состояния без вызова VLM: фрагмент 64×64 почти не изменился и с вопроса прошло < MAX_REUSE_SEC
REUSE_PIX_DIFF, REUSE_FRAC, MAX_REUSE_SEC = 20, 0.04, 8.0
# сколько замеров подряд должно длиться «рабочее место пусто» / «сейф открыт без работы с ним»
MIN_AWAY_STATES = 2

PERSON = {"сидит": "sit", "стоит": "stand", "нет": "none"}
SCREEN = {"программа": "app", "блокировка": "lock", "тёмный": "dark", "темный": "dark", "закрыт": "closed"}
ACTION = {"пьёт": "drink", "пьет": "drink", "ест": "drink", "телефон": "phone", "другое": "other", "нет": "none"}


@dataclass
class DeskState:
    t: float
    person: str          # кассир: sit | stand | none | ?
    screen: str          # app | lock | dark | closed | ?
    client: str          # клиент напротив: sit | stand | none | ?
    action: str          # drink | phone | other | none
    personal: bool       # личные вещи (сумка, рюкзак, одежда) на рабочем столе
    cash: bool
    bag: bool
    safe_open: bool | None
    note: str
    reused: bool = False  # состояние повторено с прошлого замера без вызова VLM (картинка не менялась)

    @property
    def present(self) -> bool:
        return self.person in ("sit", "stand")


def _iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def find_roi(dets: list[list[Det]], width: int, height: int) -> tuple[int, int, int, int] | None:
    """Область рабочего места: самое устойчивое положение ноутбука, расширенное до стола."""
    boxes = [d.box for ds in dets for d in ds if d.group == "laptop"]
    if not boxes:
        return None
    # ноутбук стоит на месте: берём кластер рамок, который встречается чаще всего
    support = [sum(_iou(b, o) > 0.3 for o in boxes) for b in boxes]
    anchor = boxes[int(np.argmax(support))]
    x1, y1, x2, y2 = np.median(np.array([b for b in boxes if _iou(b, anchor) > 0.3]), axis=0)
    bw, bh = x2 - x1, y2 - y1
    kl, kt, kr, kb = ROI_EXPAND
    return (max(0, int(x1 - bw * kl)), max(0, int(y1 - bh * kt)),
            min(width, int(x2 + bw * kr)), min(height, int(y2 + bh * kb)))


def crop(img: np.ndarray, roi) -> np.ndarray:
    x1, y1, x2, y2 = roi
    c = img[y1:y2, x1:x2]
    s = CROP_SIDE / max(c.shape[:2])
    return cv2.resize(c, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC if s > 1 else cv2.INTER_AREA)


def ask_state(vlm: VLMClient, frame: Frame, roi) -> DeskState:
    raw = vlm.ask(PROMPT, [to_jpeg_b64(crop(frame.image, roi), CROP_SIDE, 92)])
    d = _extract_json(raw)
    norm = lambda v: str(v or "").strip().lower()  # noqa: E731
    safe = norm(d.get("safe"))
    return DeskState(
        t=frame.t,
        person=PERSON.get(norm(d.get("person")), "?"),
        screen=SCREEN.get(norm(d.get("screen")), "?"),
        client=PERSON.get(norm(d.get("client")), "?"),
        action=ACTION.get(norm(d.get("action")), "other"),
        personal=norm(d.get("personal")) == "да",
        cash=norm(d.get("cash")) == "да",
        bag=norm(d.get("bag")) == "да",
        safe_open=True if safe.startswith("откр") else False if safe.startswith("закр") else None,
        note=str(d.get("note", "")).strip(),
    )


def _key(s: DeskState) -> tuple:
    return s.present, s.screen, s.cash, s.bag, s.safe_open


def scan(vlm: VLMClient, frames: list[Frame], roi, step_sec: float = 2.0, max_calls: int = 26,
         coarse_points: int = 20, deadline_ok=lambda: True) -> list[DeskState]:
    """Дорожка состояний рабочего места не дороже max_calls вызовов VLM на видео.

    1) грубый проход: шаг max(step_sec, длительность / coarse_points) — у видео до 40 с это и есть step_sec;
    2) уточнение: между соседними замерами, где состояние изменилось (ушла, экран, сейф…), — шаг step_sec.
    На неизменной картинке (фрагмент 64×64 почти тот же, с вопроса < MAX_REUSE_SEC) состояние повторяется без вызова.
    """
    if not frames:
        return []
    calls = 0

    def small(f: Frame) -> np.ndarray:
        return cv2.cvtColor(cv2.resize(crop(f.image, roi), (64, 64), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)

    def run(picks: list[Frame], prev: tuple | None) -> list[DeskState]:
        """Состояния для кадров picks по порядку; prev — (состояние, фрагмент) последнего вопроса для повтора."""
        nonlocal calls
        out = []
        for f in picks:
            sm = small(f)
            if prev and f.t - prev[0].t < MAX_REUSE_SEC and float((cv2.absdiff(sm, prev[1]) > REUSE_PIX_DIFF).mean()) < REUSE_FRAC:
                out.append(replace(prev[0], t=f.t, reused=True))
                continue
            if calls >= max_calls or not deadline_ok():
                log.warning("Лимит скана рабочего места: %d вызовов, остановлен на %.1f с", calls, f.t)
                break
            try:
                st = ask_state(vlm, f, roi)
            except Exception as e:  # одна ошибка VLM не должна ронять видео
                log.warning("VLM ошибка (рабочее место, t=%.1f): %s", f.t, e)
                continue
            calls += 1
            out.append(st)
            prev = (st, sm)
        return out

    def every(t0: float, t1: float, step: float) -> list[Frame]:
        picks, next_t = [], t0
        for f in frames:
            if t0 - 1e-6 <= f.t <= t1 + 1e-6 and f.t + 1e-6 >= next_t:
                picks.append(f)
                next_t = f.t + step
        return picks

    coarse_step = max(step_sec, frames[-1].t / max(1, coarse_points))
    states = run(every(0.0, frames[-1].t, coarse_step), None)
    if coarse_step > step_sec:
        extra = []
        for a, b in zip(states, states[1:]):
            if _key(a) != _key(b):
                extra += run(every(a.t + step_sec, b.t - step_sec / 2, step_sec), None)
        states = sorted(states + extra, key=lambda s: s.t)
    log.info("Скан рабочего места: %d замеров, %d вызовов VLM", len(states), calls)
    return states


def _runs(states: list[DeskState], pred) -> list[tuple[int, int]]:
    """Отрезки подряд идущих состояний, где pred истинно: [(i_start, i_end_inclusive)]."""
    runs, start = [], None
    for i, s in enumerate(states):
        if pred(s) and start is None:
            start = i
        if not pred(s) and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(states) - 1))
    return runs


def _leave_time(states: list[DeskState], i0: int) -> float:
    """Момент ухода по конвенции разметки — когда кассир встаёт и уходит.

    Перед пустым столом обычно идёт отрезок «стоит». Короткий (≤ 3 с) — встала и пошла: время между
    «сидит» и первым «стоит». Длинный — работала стоя (у сейфа): время последнего «стоит».
    """
    k = i0
    while k > 0 and states[k - 1].person == "stand":
        k -= 1
    if k == i0:  # сразу «сидит» → «нет»
        return (states[i0 - 1].t + states[i0].t) / 2
    if states[i0 - 1].t - states[k].t <= 3.0:
        return (states[k - 1].t + states[k].t) / 2 if k > 0 else states[k].t
    return states[i0 - 1].t


def phone_times(frames: list[Frame], dets: list[list[Det]], roi) -> list[float]:
    """Моменты, когда детектор видит телефон внутри рабочего места — подтверждение для T15."""
    x1, y1, x2, y2 = roi
    out = []
    for f, ds in zip(frames, dets):
        for d in ds:
            cx, cy = d.center
            if d.group == "phone" and x1 <= cx <= x2 and y1 <= cy <= y2:
                out.append(f.t)
                break
    return out


def desk_findings(states: list[DeskState], phones: list[float] | None = None) -> list[dict]:
    """T01–T03 по дорожке состояний: кассир был на месте, потом рабочее место пусто; сейф открыт без работы с ним."""
    found: list[dict] = []
    for i0, i1 in _runs(states, lambda s: not s.present):
        if i0 == 0:
            continue  # пусто с самого начала — ухода не видели (кассир ещё не пришёл)
        if i1 - i0 + 1 < MIN_AWAY_STATES:
            continue  # один пустой замер — кассир наклонилась/вышла из фрагмента на секунду (Х-12, Х-25)
        away = states[i0:i1 + 1]
        t_leave = _leave_time(states, i0)
        n = len(away)
        # п. 22 Правил № 231: клиент остаётся у стола, а кассира нет
        if sum(s.client in ("sit", "stand") for s in away) >= MIN_AWAY_STATES:
            found.append({"code": "T16", "t": t_leave, "confidence": 0.75,
                          "observed": "Кассир встаёт и уходит с рабочего места, клиент остаётся у стола без кассира"})
        if sum(s.screen == "app" for s in away) >= max(1, (n + 1) // 2):
            found.append({"code": "T01", "t": t_leave, "confidence": 0.8,
                          "observed": "Кассир уходит с рабочего места; на экране ноутбука остаётся открытое окно программы, "
                                      "экран не заблокирован"})
        if any(s.cash for s in away) or any(s.bag for s in away):
            what = "наличные" if any(s.cash for s in away) else "сумка/пакет"
            found.append({"code": "T02", "t": t_leave, "confidence": 0.75,
                          "observed": f"Кассир уходит с рабочего места; на столе остаются {what} без присмотра"})
    # сейф открыт ≥ 2 замеров подряд, а кассир при этом не работает с ним (сидит за столом или ушёл)
    for i0, i1 in _runs(states, lambda s: s.safe_open is True):
        if i1 - i0 < 1:
            continue  # один кадр — открыла и закрыла, это норма
        idle_all = [i for i in range(i0, i1 + 1) if states[i].person in ("sit", "none")]
        if len(idle_all) < MIN_AWAY_STATES:
            continue  # сейф открыт, пока с ним работают (стоят у него) — норма
        idle = idle_all[0]
        # «отходит от открытого сейфа»: стояла у сейфа, потом села/ушла (Х-20) — или кассира нет совсем.
        # Сидит всё время рядом с открытым сейфом (ракурс A: сейф у кресла, Х-5, Х-19) — работает с ним, норма.
        walked_away = any(states[i].person == "stand" for i in range(i0, idle))
        if not walked_away and sum(states[i].person == "none" for i in idle_all) < MIN_AWAY_STATES:
            continue
        t = (states[idle - 1].t + states[idle].t) / 2 if idle > 0 else states[idle].t
        found.append({"code": "T03", "t": t, "confidence": 0.75,
                      "observed": "Кассир отходит от сейфа; дверца сейфа остаётся открытой" +
                                  (", кассир работает за столом" if states[idle].person == "sit" else "")})

    # T14/T15/T13 — действия кассира и вещи на столе; считаем только настоящие ответы VLM, не повторы
    asked = [s for s in states if not s.reused]
    # телефон VLM часто «видит» у клиента или в пустых руках — засчитываем, только если детектор тоже видит
    # телефон на рабочем месте в пределах 3 с (phones=None — подтверждения нет, верим VLM)
    phone_ok = (lambda s: True) if phones is None else (lambda s: any(abs(s.t - t) <= 3.0 for t in phones))  # noqa: E731
    rules = [
        ("T14", lambda s: s.action == "drink", 1, 0.7, "Кассир пьёт или ест на рабочем месте"),
        ("T15", lambda s: s.action == "phone" and phone_ok(s), 2, 0.7,
         "Кассир держит в руке мобильный телефон (смартфон) на рабочем месте"),
        # пока кассир стоит, вещи могут быть просто в руках (вошла с сумкой) — считаем, когда села или отошла;
        # 3 подтверждения: инкассаторскую сумку на столе модель иногда принимает за личную (Х-16 — 2 раза)
        # при клиенте/инкассаторе напротив сумка на столе скорее его (Х-16), а не личная вещь кассира
        ("T13", lambda s: s.personal and s.person in ("sit", "none") and s.client == "none", 3, 0.65,
         "На рабочем столе кассира лежат личные вещи (сумка, рюкзак или верхняя одежда)"),
    ]
    for code, pred, need, conf, observed in rules:
        hits = [s for s in asked if pred(s)]
        if len(hits) < need:
            continue
        t = hits[0].t
        if code == "T14" and any(s.cash and abs(s.t - t) <= 10 for s in states):
            observed += "; на столе рядом лежат наличные"
        found.append({"code": code, "t": t, "confidence": conf, "observed": observed})
    return found
