"""Рабочее место кассира: где оно на кадре и что на нём происходит.

Ноутбук детектор находит на всех ракурсах - вокруг него вырезаем фрагмент стола, увеличиваем и
задаём VLM простые вопросы о состоянии (кто за столом, что на экране, деньги, сумка, сейф).
Нарушения T01–T03 выводят правила по дорожке состояний, а не VLM: вопрос «найди нарушение»
маленькая модель отвечает выдумками, а вопрос о факте на увеличенном фрагменте - почти без ошибок.
Ручных зон нет - всё от положения ноутбука, поэтому новый ракурс не ломает логику.
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

# расширение рамки ноутбука (в его ширинах/высотах): влево, вверх, вправо, вниз - захватываем стол и сейф рядом
ROI_EXPAND = (1.2, 1.2, 1.2, 1.5)
# без ноутбука: расширение рамки сидящего кассира (по ширине, по высоте) - захватываем стол перед ним
SEAT_EXPAND = (0.9, 0.5)
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
        # нераспознанный ответ («?») - не повод утверждать, что кассира нет: считаем, что он на месте
        return self.person != "none"


def _iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _seat_roi(dets: list[list[Det]], width: int, height: int) -> tuple[int, int, int, int] | None:
    """Запасной ориентир без ноутбука: место, где человек дольше всего неподвижен (кассир за столом).

    Отражения в стекле тоже неподвижны, но мелкие - поэтому выбираем по «число кадров × площадь рамки».
    """
    boxes = [d.box for ds in dets for d in ds if d.group == "person" and d.score >= 0.5]
    boxes = boxes[::max(1, len(boxes) // 300)]  # сравнение «каждая с каждой» - не больше ~300 рамок
    if len(boxes) < 5:
        return None
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])  # noqa: E731
    best = max(boxes, key=lambda b: sum(_iou(b, o) > 0.5 for o in boxes) * area(b))
    if sum(_iou(best, o) > 0.5 for o in boxes) < 5:
        return None  # никто не задерживается на месте - рабочего места не видно
    x1, y1, x2, y2 = np.median(np.array([b for b in boxes if _iou(b, best) > 0.5]), axis=0)
    bw, bh = x2 - x1, y2 - y1
    return (max(0, int(x1 - bw * SEAT_EXPAND[0])), max(0, int(y1 - bh * SEAT_EXPAND[1])),
            min(width, int(x2 + bw * SEAT_EXPAND[0])), min(height, int(y2 + bh * SEAT_EXPAND[1])))


def find_roi(dets: list[list[Det]], width: int, height: int) -> tuple[int, int, int, int] | None:
    """Область рабочего места: самое устойчивое положение ноутбука, расширенное до стола.

    Ноутбука нет в кадре (другой ракурс, ракурс C) - берём место, где дольше всего неподвижен человек.
    """
    boxes = [d.box for ds in dets for d in ds if d.group == "laptop"]
    boxes = boxes[::max(1, len(boxes) // 300)]  # сравнение «каждая с каждой» - не больше ~300 рамок
    # ноутбук стоит на месте: берём кластер рамок, который встречается чаще всего
    support = [sum(_iou(b, o) > 0.3 for o in boxes) for b in boxes]
    if not boxes or max(support) < 3:
        # ноутбука нет или это одна случайная рамка (счётная машина, стекло) - ищем по сидящему кассиру
        return _seat_roi(dets, width, height)
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
         coarse_points: int = 20, deadline_ok=lambda: True, on_call=None, stats: dict | None = None) -> list[DeskState]:
    """Дорожка состояний рабочего места не дороже max_calls вызовов VLM на видео.

    1) грубый проход: шаг max(step_sec, длительность / coarse_points) - у видео до 40 с это и есть step_sec;
    2) уточнение: между соседними замерами, где состояние изменилось (ушла, экран, сейф…), - шаг step_sec.
    На неизменной картинке (фрагмент 64×64 почти тот же, с вопроса < MAX_REUSE_SEC) состояние повторяется без вызова.
    """
    if not frames:
        return []
    calls, errors, errors_in_row = 0, 0, 0

    def small(f: Frame) -> np.ndarray:
        return cv2.cvtColor(cv2.resize(crop(f.image, roi), (64, 64), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)

    def run(picks: list[Frame], prev: tuple | None) -> list[DeskState]:
        """Состояния для кадров picks по порядку; prev - (состояние, фрагмент) последнего вопроса для повтора."""
        nonlocal calls, errors, errors_in_row
        out = []
        for f in picks:
            sm = small(f)
            if prev and f.t - prev[0].t < MAX_REUSE_SEC and float((cv2.absdiff(sm, prev[1]) > REUSE_PIX_DIFF).mean()) < REUSE_FRAC:
                out.append(replace(prev[0], t=f.t, reused=True))
                continue
            if calls >= max_calls or not deadline_ok() or errors_in_row >= 2:
                log.warning("Скан рабочего места остановлен на %.1f с: вызовов %d, ошибок подряд %d",
                            f.t, calls, errors_in_row)
                break
            calls += 1  # неудачный вызов тоже тратит время - считаем в лимит
            if on_call:
                on_call(calls)  # прогресс после каждого вопроса: без него сторож backend убьёт «зависшую» задачу
            try:
                st = ask_state(vlm, f, roi)
            except Exception as e:  # одна ошибка VLM не должна ронять видео; две подряд - модель недоступна
                errors, errors_in_row = errors + 1, errors_in_row + 1
                log.warning("VLM ошибка (рабочее место, t=%.1f): %s", f.t, e)
                continue
            errors_in_row = 0
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
    log.info("Скан рабочего места: %d замеров, %d вызовов VLM, ошибок %d", len(states), calls, errors)
    if stats is not None:
        stats.update(calls=calls, errors=errors)
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
    """Момент ухода по конвенции разметки - когда кассир встаёт и уходит.

    Перед пустым столом обычно идёт отрезок «стоит». Короткий (≤ 3 с) - встала и пошла: время между
    «сидит» и первым «стоит». Длинный - работала стоя (у сейфа): время последнего «стоит».
    """
    k = i0
    while k > 0 and states[k - 1].person == "stand":
        k -= 1
    if k == i0:  # сразу «сидит» → «нет»
        return (states[i0 - 1].t + states[i0].t) / 2
    if states[i0 - 1].t - states[k].t <= 3.0:
        return (states[k - 1].t + states[k].t) / 2 if k > 0 else states[k].t
    return states[i0 - 1].t


LEFT_PROMPT = (ML_DIR / "prompts" / "left_items_ru.txt").read_text(encoding="utf-8")
# что модель иногда всё равно перечисляет, хотя это обычное оборудование стола
EQUIPMENT = ("ноутбук", "компьютер", "монитор", "телефон", "счётн", "счетн", "машин", "мыш", "клавиатур", "принтер",
             "сейф", "терминал", "наушник", "провод", "кабел")


def _left_items(vlm: VLMClient, frame: Frame, roi) -> set[str]:
    d = _extract_json(vlm.ask(LEFT_PROMPT, [to_jpeg_b64(crop(frame.image, roi), CROP_SIDE, 92)]))
    items = {x.strip().strip(".").lower() for x in str(d.get("left_items", "")).replace(";", ",").split(",")}
    return {x for x in items if x and x not in ("ничего", "нет") and not any(w in x for w in EQUIPMENT)}


def left_items_findings(vlm: VLMClient, frames: list[Frame], roi, states: list[DeskState]) -> list[dict]:
    """T02 по узкому вопросу после ухода кассира: «что, кроме оборудования, оставлено на столе?».

    Поля cash/bag общего скана пропускают журнал, планшет, банку (Х-24); узкий вопрос их называет, а на
    нормальных видео отвечает «ничего» или перечисляет оборудование. Засчитываем предмет, названный на двух
    кадрах после ухода (одиночная выдумка отсеивается).
    """
    found = []
    for i0, i1 in _runs(states, lambda s: not s.present):
        if i0 == 0 or i1 - i0 + 1 < MIN_AWAY_STATES:
            continue
        times = [states[i0].t, states[min(i1, i0 + 2)].t]
        picks = [min(frames, key=lambda f: abs(f.t - t)) for t in times]
        try:
            answers = [_left_items(vlm, f, roi) for f in picks]
        except Exception as e:
            log.warning("VLM ошибка (оставленные предметы): %s", e)
            continue
        items = sorted(set.intersection(*answers)) if len(picks) > 1 else sorted(answers[0])
        log.info("После ухода в %.1f с на столе: %s → %s", states[i0].t, answers, items)
        if items:
            found.append({"code": "T02", "t": _leave_time(states, i0), "confidence": 0.8,
                          "observed": "Кассир уходит с рабочего места; на столе остаются без присмотра: " + ", ".join(items)})
    return found


def phone_times(frames: list[Frame], dets: list[list[Det]], roi) -> list[float]:
    """Моменты, когда детектор видит телефон в руке кассира на рабочем месте - подтверждение для T15.

    Кассир - человек, ближайший к центру рабочего места (оно строится вокруг ноутбука / сидящего кассира).
    Телефон засчитывается, если ближе всего он к кассиру: телефон в руке клиента напротив (Х-5) - не нарушение
    кассира, телефон без людей рядом (мышь на пустом столе) - не «в руке».
    """
    x1, y1, x2, y2 = roi
    rc = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
    out = []
    for f, ds in zip(frames, dets):
        persons = [np.array(p.center) for p in ds if p.group == "person" and p.score >= 0.4]
        if not persons:
            continue
        cashier = min(range(len(persons)), key=lambda i: np.linalg.norm(persons[i] - rc))
        for d in ds:
            cx, cy = d.center
            if d.group != "phone" or not (x1 <= cx <= x2 and y1 <= cy <= y2):
                continue
            nearest = min(range(len(persons)), key=lambda i: np.linalg.norm(persons[i] - np.array((cx, cy))))
            if nearest == cashier:
                out.append(f.t)
                break
    return out


def desk_findings(states: list[DeskState], phones: list[float] | None = None) -> list[dict]:
    """T01–T03 по дорожке состояний: кассир был на месте, потом рабочее место пусто; сейф открыт без работы с ним."""
    found: list[dict] = []
    for i0, i1 in _runs(states, lambda s: not s.present):
        if i0 == 0:
            continue  # пусто с самого начала - ухода не видели (кассир ещё не пришёл)
        if i1 - i0 + 1 < MIN_AWAY_STATES:
            continue  # один пустой замер - кассир наклонилась/вышла из фрагмента на секунду (Х-12, Х-25)
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
            continue  # один кадр - открыла и закрыла, это норма
        idle_all = [i for i in range(i0, i1 + 1) if states[i].person in ("sit", "none")]
        if len(idle_all) < MIN_AWAY_STATES:
            continue  # сейф открыт, пока с ним работают (стоят у него) - норма
        idle = idle_all[0]
        # «отходит от открытого сейфа»: стояла у сейфа, потом села/ушла (Х-20) - или кассира нет совсем.
        # Сидит всё время рядом с открытым сейфом (ракурс A: сейф у кресла, Х-5, Х-19) - работает с ним, норма.
        walked_away = any(states[i].person == "stand" for i in range(i0, idle))
        if not walked_away and sum(states[i].person == "none" for i in idle_all) < MIN_AWAY_STATES:
            continue
        t = (states[idle - 1].t + states[idle].t) / 2 if idle > 0 else states[idle].t
        found.append({"code": "T03", "t": t, "confidence": 0.75,
                      "observed": "Кассир отходит от сейфа; дверца сейфа остаётся открытой" +
                                  (", кассир работает за столом" if states[idle].person == "sit" else "")})

    # T14/T15/T13 - действия кассира и вещи на столе; считаем только настоящие ответы VLM, не повторы
    asked = [s for s in states if not s.reused]
    # телефон VLM часто «видит» у клиента или в пустых руках - засчитываем, только если детектор тоже видит
    # телефон на рабочем месте в пределах 3 с (phones=None - подтверждения нет, верим VLM)
    phone_ok = (lambda s: True) if phones is None else (lambda s: any(abs(s.t - t) <= 3.0 for t in phones))  # noqa: E731
    rules = [
        ("T14", lambda s: s.action == "drink", 1, 0.7, "Кассир пьёт или ест на рабочем месте"),
        ("T15", lambda s: s.action == "phone" and phone_ok(s), 2, 0.7,
         "Кассир держит в руке мобильный телефон (смартфон) на рабочем месте"),
        # пока кассир стоит, вещи могут быть просто в руках (вошла с сумкой) - считаем, когда села или отошла;
        # 3 подтверждения: инкассаторскую сумку на столе модель иногда принимает за личную (Х-16 - 2 раза)
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
