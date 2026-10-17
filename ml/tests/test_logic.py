"""Логика без нейросетей: кандидаты, правила детектора, слияние, сборка ответа. Запуск: pytest -q"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml import kb  # noqa: E402
from ml.detector import Det  # noqa: E402
from ml.pipeline import _merge, to_violation  # noqa: E402
from ml.schema import validate_result  # noqa: E402
from ml.signals import compute_signals, cv_findings, find_candidates  # noqa: E402
from ml.video import Frame  # noqa: E402


def _frames(n=40, fps=2.0):
    img = np.full((848, 464, 3), 60, np.uint8)
    return [Frame(t=i / fps, index=i * 15, image=img) for i in range(n)]


def test_kb_complete():
    for code in kb.type_codes():
        r = kb.rule_of(code)
        assert r["type_name"] and r["visual"] and r["why"], code
        assert kb.build_description(code, "Кассир уходит")


def test_candidates_person_leaves_and_phone():
    frames = _frames()
    dets = []
    for i, f in enumerate(frames):
        d = [Det("person", "person", 0.9, (100, 400, 250, 700))] if i < 20 else []
        if 10 <= i < 30:
            d.append(Det("phone", "cell phone", 0.8, (150, 500, 180, 540)))
        dets.append(d)
    sig = compute_signals(frames, dets)
    cands = find_candidates(sig, duration=20, frame_diag=966, window_sec=6, max_calls=12)
    reasons = " | ".join(c.reason for c in cands)
    assert "выход" in reasons and "телефон" in reasons
    found = {f["code"] for f in cv_findings(sig)}
    assert "T15" in found


def test_merge_and_violation_schema():
    frames = _frames()
    raw = [{"code": "T02", "t": 9.0, "confidence": 0.6, "observed": "a"},
           {"code": "T02", "t": 10.5, "confidence": 0.9, "observed": "b"},
           {"code": "T01", "t": 10.0, "confidence": 0.7, "observed": "c"}]
    merged = _merge(raw, 5.0)
    assert len(merged) == 2
    t02 = next(m for m in merged if m["code"] == "T02")
    assert t02["t"] == 9.0 and t02["confidence"] == 0.9 and t02["observed"] == "b"

    from ml.config import get_settings
    viols = [to_violation(m, frames, get_settings()) for m in merged]
    res = {"verdict": "violation", "violations": viols}
    assert validate_result(res) == []
