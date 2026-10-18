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
    # смена любого из этих признаков между грубыми замерами - повод уточнить отрезок с шагом 2 с;
    # клиент пришёл/ушёл - для T07 (деньги прошлого клиента при входе следующего)
    return s.present, s.client in ("sit", "stand"), s.screen, s.cash, s.bag, s.safe_open


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


def client_findings(states: list[DeskState]) -> list[dict]:
    """T07 по дорожке «клиент / деньги на столе»: клиент №1 ушёл, наличные всё время лежат на столе, подходит клиент №2.

    Клиент - отрезок client in (sit, stand) от MIN_AWAY_STATES замеров подряд. Деньги должны быть видны в последнем
    замере клиента №1, во всей паузе между клиентами и в первом замере клиента №2 - без этого условия любая смена
    клиентов давала бы тревогу (на нормальных видео деньги на столе между клиентами не лежат).
    Таймкод - момент подхода клиента №2: середина между последним замером паузы и первым замером, где он уже у стола
    (по разметке нарушение видно, когда «входит следующий клиент», то есть раньше, чем он сел).
    """
    found = []
    visits = _visits(states)
    for (_, b1), (a2, _) in zip(visits, visits[1:]):
        gap = states[b1 + 1:a2]
        if gap and states[b1].cash and all(s.cash for s in gap) and states[a2].cash:
            found.append({"code": "T07", "t": (states[a2 - 1].t + states[a2].t) / 2, "confidence": 0.7,
                          "observed": "Предыдущий клиент ушёл, наличные остались на столе; "
                                      "к столу подходит следующий клиент"})
    # T09 (п. 20 Правил № 231): клиент уходит в тот момент, когда кассир встаёт работать с его деньгами (Х-34:
    # кассир сидит при клиенте, клиент уходит, кассир уже стоит у счётной машины). Если кассир стоял и до ухода
    # клиента (Х-35, норма) - это не «встала посреди операции». Правило по одному обучающему примеру - гипотеза.
    for _, b in visits:
        if b + 1 < len(states) and states[b].person == "sit" and states[b + 1].person == "stand":
            found.append({"code": "T09", "t": (states[b].t + states[b + 1].t) / 2, "confidence": 0.6,
                          "observed": "Клиент уходит от стола, когда кассир встаёт и продолжает работу "
                                      "(возможно, пересчёт его денег); на видео не зафиксировано, что операция "
                                      "завершена при клиенте"})
    return found


# T11: визит второго человека (инкассатора) от и до стольких секунд; сумка на столе в окне [уход - 2 с, уход + 6 с]
DROP_VISIT_SEC, DROP_WINDOW = (2.0, 15.0), (2.0, 6.0)


def bag_drop_findings(states: list[DeskState], company: list[float], duration: float,
                      bag_times: list[float]) -> list[dict]:
    """T11: второй человек (инкассатор) подходит, оставляет сумку на столе и вскоре уходит - без передачи документов.

    Х-17: инкассатор у стола 4–11.5 с, сумка на столе и после его ухода. В норме (Х-16) инкассатор ждёт у стола с
    документами до конца - визит не короткий и не заканчивается уходом. Визиты - по детектору (company_times), сумка -
    по ответам VLM. Сумку должны принести: bag_times - кадры, где детектор видит сумку; раньше чем за 2 с до визита
    её быть не должно (Х-14, Х-13: кассир весь ролик работает с сумками, VLM замечает их не сразу).
    Правило по одному обучающему примеру - гипотеза.
    """
    found, runs, start, prev = [], [], None, None
    for t in company:
        if start is None:
            start = t
        elif t - prev > 1.1:  # пропуск больше двух кадров - визит закончился
            runs.append((start, prev))
            start = t
        prev = t
    if start is not None:
        runs.append((start, prev))
    for a, b in runs:
        if not DROP_VISIT_SEC[0] <= b - a <= DROP_VISIT_SEC[1] or duration - b < 2.0:
            continue  # мимолётная рамка, долгий визит или человек у стола до конца видео
        if any(t < a - 2.0 for t in bag_times) or any(s.bag for s in states if s.t < a):
            continue  # сумка была до визита - её не принесли
        bags = [s for s in states if s.bag and b - DROP_WINDOW[0] <= s.t <= b + DROP_WINDOW[1]]
        if len(bags) >= 2:
            found.append({"code": "T11", "t": (a + b) / 2, "confidence": 0.6,
                          "observed": "К столу подходит второй человек (возможно, инкассатор), на столе остаётся сумка, "
                                      "и он вскоре уходит; передача и проверка документов на видео не зафиксированы"})
    return found


# T12: пересчёт содержимого инкассаторских сумок (полистно, вручную или на машинке) + сверка - не меньше этого
COUNT_MIN_SEC = 30.0


def safe_without_count_findings(states: list[DeskState]) -> list[dict]:
    """T12: после вскрытия инкассаторских сумок деньги ушли в сейф, не пролежав на столе столько, сколько нужно на
    пересчёт. Х-13: сумки → деньги на столе 23–42 с (19 с) → сейф 49 с; норма Х-14: деньги на столе 36–98 с (62 с),
    кассир пересчитывает руками, сейф - 120 с. Только без клиента (это не обслуживание) и только по цепочке
    «сумки → деньги → открытый сейф»: на остальных 40 обучающих видео такой цепочки нет."""
    if _visits(states):
        return []
    bags = [s for s in states if s.bag]
    if len(bags) < 2:
        return []
    safe = [s for s in states if s.safe_open is True and s.t > bags[0].t]
    if not safe:
        return []
    cash = [s for s in states if s.cash and bags[0].t <= s.t < safe[0].t]
    if len(cash) < 2 or cash[-1].t - cash[0].t >= COUNT_MIN_SEC:
        return []
    return [{"code": "T12", "t": (cash[-1].t + safe[0].t) / 2, "confidence": 0.6,
             "observed": f"Вложения инкассаторских сумок лежат на столе около {cash[-1].t - cash[0].t:.0f} с и "
                         "уносятся в сейф; пересчёта за это время на видео не зафиксировано"}]


def _visits(states: list[DeskState]) -> list[tuple[int, int]]:
    """Визиты клиентов: client in (sit, stand) не меньше MIN_AWAY_STATES замеров подряд."""
    has_client = lambda s: s.client in ("sit", "stand")  # noqa: E731
    return [(a, b) for a, b in _runs(states, has_client) if b - a + 1 >= MIN_AWAY_STATES]


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


# T05 по рамкам детектора: «рядом» - ближе STRANGER_NEAR роста кассира, «не отражение» - рост от STRANGER_SIZE его роста,
# держится STRANGER_RUN кадров подряд (3 с при 2 кадр/с). Подобрано на Х-18/Х-30: 0 ложных на 20 нормальных видео
STRANGER_NEAR, STRANGER_SIZE, STRANGER_RUN = 1.0, 0.8, 6


def stranger_findings(frames: list[Frame], dets: list[list[Det]], roi) -> list[dict]:
    """T05: рядом с кассиром, на его стороне стола, стоит ещё один человек.

    Кассир - человек, ближайший к центру рабочего места (медиана положения и роста по видео). «Сторона кассира» -
    полуплоскость от центра стола в сторону кассира: клиент сидит напротив, через стол, и сюда не попадает.
    Ручных зон нет: всё от найденного рабочего места и роста кассира в этом видео.
    """
    x1, y1, x2, y2 = roi
    rc = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
    ctr = lambda b: np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])  # noqa: E731
    persons = [[p for p in ds if p.group == "person" and p.score >= 0.5] for ds in dets]
    nearest_rc = [min(ps, key=lambda p: np.linalg.norm(ctr(p.box) - rc)) for ps in persons if ps]
    if len(nearest_rc) < 5:
        return []
    cpos = np.median([ctr(p.box) for p in nearest_rc], axis=0)
    ch = float(np.median([p.box[3] - p.box[1] for p in nearest_rc]))
    side = cpos - rc  # направление «стол → кассир»
    run = 0
    for i, (f, ps) in enumerate(zip(frames, persons)):
        ok = False
        if len(ps) >= 2:
            cashier = min(ps, key=lambda p: np.linalg.norm(ctr(p.box) - cpos))
            ok = any(np.dot(ctr(p.box) - rc, side) > 0                                     # сторона кассира
                     and np.linalg.norm(ctr(p.box) - ctr(cashier.box)) < STRANGER_NEAR * ch  # вплотную к кассиру
                     and (p.box[3] - p.box[1]) >= STRANGER_SIZE * ch                         # не мелкое отражение
                     for p in ps if p is not cashier)
        run = run + 1 if ok else 0
        if run == STRANGER_RUN:
            # таймкод - когда стало видно, что посторонний задержался рядом (Х-18: разметка 20 с, появился 15.5 с)
            return [{"code": "T05", "t": f.t, "confidence": 0.6, "source": "detector",
                     "observed": "Рядом с кассиром, на служебной стороне стола, находится ещё один человек "
                                 "(не клиент напротив) и держится рядом не меньше 3 секунд"}]
    return []


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


# второй человек в кадре для T13: уверенная рамка (слабые 0.5–0.6 - фон и отражения, Х-40), не меньше этой доли
# медианного роста людей в видео, не дубль другой рамки (детектор иногда обводит одного человека дважды, Х-40 19 с)
# и держится 2 кадра подряд
COMPANY_SCORE, COMPANY_SIZE, COMPANY_DUP_IOU, COMPANY_NEAR_SEC = 0.7, 0.5, 0.5, 2.0


def company_times(frames: list[Frame], dets: list[list[Det]]) -> list[float]:
    """Моменты, когда в кадре кроме кассира есть ещё человек (клиент, инкассатор) - по детектору.

    Сумка на столе при втором человеке рядом - скорее его (Х-16: инкассатор кладёт сумку и ждёт с документами;
    VLM трижды называет её «личной», а поле client пропускает инкассатора, стоящего не на месте клиента).
    """
    persons = [[p for p in ds if p.group == "person" and p.score >= COMPANY_SCORE] for ds in dets]
    heights = [p.box[3] - p.box[1] for ps in persons for p in ps]
    if not heights:
        return []
    h = float(np.median(heights))
    two = []
    for ps in persons:
        kept: list[Det] = []
        for p in sorted(ps, key=lambda p: -p.score):
            if p.box[3] - p.box[1] >= COMPANY_SIZE * h and all(_iou(p.box, k.box) <= COMPANY_DUP_IOU for k in kept):
                kept.append(p)
        two.append(len(kept) >= 2)
    return [f.t for i, f in enumerate(frames)
            if two[i] and ((i > 0 and two[i - 1]) or (i + 1 < len(two) and two[i + 1]))]


def desk_findings(states: list[DeskState], phones: list[float] | None = None,
                  company: list[float] | None = None, drinks: list[float] | None = None) -> list[dict]:
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
    # «пьёт» - один ответ VLM; засчитываем, только если детектор в пределах 3 с видит напиток или еду (Х-16 после
    # чёрного экрана: «пьёт» на одном кадре, стакана нет). drinks=None - подтверждения нет, верим VLM
    drink_ok = (lambda s: True) if drinks is None else (lambda s: any(abs(s.t - t) <= 3.0 for t in drinks))  # noqa: E731
    # личные вещи засчитываем, только когда кассир у стола одна: при втором человеке рядом сумка скорее его
    alone = (lambda s: True) if company is None else (  # noqa: E731
        lambda s: not any(abs(s.t - t) <= COMPANY_NEAR_SEC for t in company))
    rules = [
        ("T14", lambda s: s.action == "drink" and drink_ok(s), 1, 0.7, "Кассир пьёт или ест на рабочем месте"),
        ("T15", lambda s: s.action == "phone" and phone_ok(s), 2, 0.7,
         "Кассир держит в руке мобильный телефон (смартфон) на рабочем месте"),
        # пока кассир стоит, вещи могут быть просто в руках (вошла с сумкой) - считаем, когда села или отошла;
        # 3 подтверждения: инкассаторскую сумку на столе модель иногда принимает за личную (Х-16 - 2 раза)
        # при клиенте/инкассаторе напротив сумка на столе скорее его (Х-16), а не личная вещь кассира
        ("T13", lambda s: s.personal and s.person in ("sit", "none") and s.client == "none" and alone(s), 3, 0.65,
         "На рабочем столе кассира лежат личные вещи (сумка, рюкзак или верхняя одежда)"),
    ]
    for code, pred, need, conf, observed in rules:
        hits = [s for s in asked if pred(s)]
        if len(hits) < need:
            continue
        t = hits[0].t
        if code == "T13":
            # вещи кладут на стол раньше, чем кассир садится: середина между началом отрезка «личные вещи на столе»
            # и первым засчитанным замером (Х-40: вещи с 14 с, села с 20 с, разметка 17 с). Не начало отрезка: стоя
            # с сумкой в руках модель тоже отвечает «вещи на столе», и отрезок уезжает назад (Х-40 на искажениях: 6 с)
            i = states.index(hits[0])
            while i > 0 and states[i - 1].personal:
                i -= 1
            t = (states[i].t + hits[0].t) / 2
        if code == "T14" and any(s.cash and abs(s.t - t) <= 10 for s in states):
            observed += "; на столе рядом лежат наличные"
        found.append({"code": code, "t": t, "confidence": conf, "observed": observed})
    return found
