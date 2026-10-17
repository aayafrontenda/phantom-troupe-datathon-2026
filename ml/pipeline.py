"""Главная точка входа ML: analyze(path) -> dict в формате раздела 10 ТЗ (+ доп. поля для интерфейса).

Этапы:
  1. кадры 2 fps (OpenCV)
  2. детектор COCO по каждому кадру -> сигналы состояния
  3. кандидаты событий (вход/выход, движение, предметы, экран без присмотра, покрытие)
  4. VLM проверяет окно вокруг каждого кандидата по чек-листу T01–T15
  5. слияние, выбор таймкода и кадров-доказательств, нормы из rules_kb.yaml
"""
from __future__ import annotations

import logging
import math
import time
from typing import Callable

from . import kb
from .config import get_settings
from .signals import Candidate, compute_signals, cv_findings, find_candidates, timeline
from .video import Frame, iter_frames, nearest, probe, to_jpeg_b64
from .entry import door_findings
from .workplace import desk_findings, find_roi, left_items_findings, phone_times, scan

log = logging.getLogger("ml.pipeline")
DESK_CALL_TIMEOUT = 25.0  # с на один вопрос скана: обычно ~1 с, до ~10 с при загрузке модели
Progress = Callable[[str, float], None]


def _noop(stage: str, progress: float) -> None:  # noqa: ARG001
    pass


def _window_frames(frames: list[Frame], t: float, width: float, n: int) -> list[Frame]:
    if n <= 1:
        return [nearest(frames, t)]
    t0 = max(0.0, t - width / 2)
    t1 = min(frames[-1].t, t + width / 2)
    picks: list[Frame] = []
    for k in range(n):
        f = nearest(frames, t0 + (t1 - t0) * k / (n - 1))
        if not picks or picks[-1].index != f.index:
            picks.append(f)
    return picks


def _merge(findings: list[dict], merge_sec: float) -> list[dict]:
    """Один тип в пределах merge_sec - одно событие: берём самое раннее время и максимальную уверенность."""
    out: list[dict] = []
    for f in sorted(findings, key=lambda x: x["t"]):
        same = next((o for o in out if o["code"] == f["code"] and abs(o["t"] - f["t"]) <= merge_sec), None)
        if same is None:
            out.append(dict(f))
            continue
        if f["confidence"] > same["confidence"]:
            same["confidence"] = f["confidence"]
            same["observed"] = f["observed"] or same["observed"]
        same["t"] = min(same["t"], f["t"])
    return out


# кадры-доказательства относительно таймкода: у «ухода» сам факт (пустое место, экран, деньги на столе) виден
# через несколько секунд после того, как кассир встал; у двери - что она так и осталась открытой
EVIDENCE_OFFSETS = {"T01": (0.0, 2.0, 5.0), "T02": (0.0, 2.0, 5.0), "T03": (0.0, 2.0, 5.0), "T16": (0.0, 2.0, 5.0),
                    "T04": (0.0, 3.0, 6.0)}


def _evidence(frames: list[Frame], t: float, s, code: str = "") -> list[dict]:
    picks: list[Frame] = []
    for dt in EVIDENCE_OFFSETS.get(code, (0.0, -1.0, 1.0)):
        f = nearest(frames, t + dt)
        if all(f.index != p.index for p in picks):
            picks.append(f)
    picks = sorted(picks[:3], key=lambda f: f.t)
    return [{"timestamp_sec": round(f.t, 2),
             "image_base64": to_jpeg_b64(f.image, s.evidence_max_side, s.evidence_jpeg_quality)} for f in picks]


def to_violation(f: dict, frames: list[Frame], s) -> dict:
    code = f["code"]
    rule = kb.rule_of(code)
    return {
        "type": rule["type_name"],
        "timecode_sec": round(float(f["t"]), 1),
        "description": kb.build_description(code, f.get("observed", "")),
        "evidence_frames": _evidence(frames, f["t"], s, code),
        # --- дополнительные поля (жюри их игнорирует, интерфейс использует) ---
        "type_code": code,
        "confidence": round(float(f["confidence"]), 2),
        "rule": {"kind": rule.get("norm_kind", "direct"), "refs": kb.refs_struct(code),
                 "caveat": rule.get("caveat")},
        "source": f.get("source", "vlm"),
    }


def analyze(path: str, on_progress: Progress | None = None, deadline: float | None = None) -> dict:
    s = get_settings()
    progress = on_progress or _noop
    started = time.time()
    # backend всегда передаёт срок «загрузка + 270 с»; свой бюджет на видео (TIME_BUDGET_SEC) действует всё равно -
    # иначе одно видео может съесть время, нужное следующим в очереди жюри
    deadline = min(deadline or float("inf"), started + s.time_budget_sec)

    info = probe(path)
    progress("frames", 0.05)
    frames = list(iter_frames(path, s.sample_fps))
    if not frames:
        raise ValueError("В видео не удалось прочитать ни одного кадра")
    duration = max(info.duration, frames[-1].t)

    # --- детектор ---
    progress("detection", 0.15)
    sig, dets = [], []
    try:
        from .detector import get_detector
        det = get_detector()
        dets = det([f.image for f in frames])
        sig = compute_signals(frames, dets)
    except Exception as e:  # нет torch/весов - работаем без детектора
        log.warning("Детектор недоступен (%s): только равномерное покрытие", e)

    diag = math.hypot(info.width or 464, info.height or 848)
    if sig:
        cands = find_candidates(sig, duration, diag, s.vlm_window_sec, s.max_vlm_calls)
    else:
        n = max(1, min(s.max_vlm_calls, int(duration // s.vlm_window_sec) + 1))
        cands = [Candidate(t=(i + 0.5) * duration / n, reason="покрытие", priority=0) for i in range(n)]

    # --- VLM ---
    findings: list[dict] = []
    vlm_calls, vlm_errors, scenes = 0, 0, []
    if dets:
        findings += door_findings(frames, dets)  # T04: дверь после входа в пустую кассу, без VLM
    from .vlm import VLMClient
    # вызов скана - около 1 с; длинный таймаут нужен только на загрузку модели в память
    vlm = VLMClient(timeout=min(s.vlm_timeout, DESK_CALL_TIMEOUT))
    roi = find_roi(dets, info.width or frames[0].image.shape[1], info.height or frames[0].image.shape[0]) if dets else None
    if vlm.enabled and roi:
        # рабочее место: дорожка состояний по увеличенному фрагменту → T01–T03 по правилам
        progress("vlm", 0.25)
        stats: dict = {}
        desk_states = scan(vlm, frames, roi, s.desk_step_sec, s.desk_max_calls,
                           deadline_ok=lambda: time.time() < deadline - DESK_CALL_TIMEOUT - 5,
                           on_call=lambda k: progress("vlm", 0.25 + 0.6 * min(1.0, k / max(1, s.desk_max_calls))),
                           stats=stats)
        vlm_errors += stats.get("errors", 0)
        for st in desk_states:
            if not st.reused:
                vlm_calls += 1
                scenes.append({"t": round(st.t, 1), "reason": "рабочее место", "scene": st.note})
        for f in desk_findings(desk_states, phone_times(frames, dets, roi)):
            findings.append({**f, "source": "vlm", "candidate": "рабочее место"})
        # после каждого ухода - узкий вопрос «что оставлено на столе» (2 вызова на уход, ~0.4 с каждый)
        if stats.get("errors", 0) < 2 and time.time() < deadline - DESK_CALL_TIMEOUT - 5:
            for f in left_items_findings(vlm, frames, roi, desk_states):
                findings.append({**f, "source": "vlm", "candidate": "уход кассира"})

    if vlm.enabled and s.vlm_generic:
        for i, c in enumerate(cands):
            if time.time() > deadline - min(s.vlm_timeout, 30):
                log.warning("Бюджет времени исчерпан: проверено %d из %d кандидатов", i, len(cands))
                break
            progress("vlm", 0.25 + 0.65 * i / max(1, len(cands)))
            win = _window_frames(frames, c.t, s.vlm_window_sec, s.vlm_frames_per_call)
            imgs = [to_jpeg_b64(f.image, s.vlm_image_side, 85) for f in win]
            try:
                res = vlm.check_window([f.t for f in win], imgs, c.hints)
                vlm_calls += 1
            except Exception as e:
                vlm_errors += 1
                log.warning("VLM ошибка на t=%.1f: %s", c.t, e)
                continue
            scenes.append({"t": round(c.t, 1), "reason": c.reason, "scene": res["scene"]})
            for f in res["findings"]:
                findings.append({"code": f["code"], "t": win[f["frame"] - 1].t, "confidence": f["confidence"],
                                 "observed": f["observed"], "source": "vlm", "candidate": c.reason})

    # без VLM - правила только по детектору (с VLM они давали ложные: счётная машина = «чемодан» → T13)
    if sig and not vlm.enabled:
        for f in cv_findings(sig):
            findings.append({**f, "source": "detector"})

    progress("report", 0.92)
    kept = [f for f in _merge(findings, s.merge_sec) if f["confidence"] >= s.min_confidence]
    violations = [to_violation(f, frames, s) for f in kept]

    tl = timeline(sig) if sig else None
    if tl and dets:
        # рамки для плеера: [группа, score, x1, y1, x2, y2] в долях кадра - не зависят от размера плеера
        tl["detections"] = [
            [[d.group, round(d.score, 2), *(round(v / dim, 4) for v, dim in zip(d.box, (w, h, w, h)))] for d in ds]
            for f, ds in zip(frames, dets) for h, w in [f.image.shape[:2]]
        ]

    return {
        "verdict": "violation" if violations else "no_violation",
        "violations": violations,
        # --- дополнительные поля ---
        "timeline": tl,
        "meta": {
            "duration_sec": round(duration, 2),
            "processing_sec": round(time.time() - started, 1),
            "frames": len(frames),
            "candidates": [{"t": round(c.t, 1), "reason": c.reason, "priority": c.priority} for c in cands],
            "vlm_calls": vlm_calls,
            "vlm_errors": vlm_errors,
            "scenes": scenes,
            "raw_findings": [{k: v for k, v in f.items()} for f in findings],
        },
    }
