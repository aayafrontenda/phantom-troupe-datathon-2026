from __future__ import annotations

import os
import time

from . import kb
from .video import frame_at, probe, to_jpeg_b64


def analyze_mock(path: str, on_progress=None, deadline=None) -> dict:  # noqa: ARG001
    delay = float(os.getenv("MOCK_DELAY", 3))
    for i, stage in enumerate(["frames", "detection", "vlm", "report"]):
        if on_progress:
            on_progress(stage, (i + 1) / 5)
        time.sleep(delay / 4)
    info = probe(path)
    dur = info.duration or 10.0
    size = os.path.getsize(path)
    violations = []
    if size % 3 != 0:
        for code, frac in (("T02", 0.4), ("T01", 0.75))[: 1 + size % 2]:
            t = round(dur * frac, 1)
            frames = []
            for dt in (-1.0, 0.0, 1.0):
                img = frame_at(path, max(0.0, t + dt))
                if img is not None:
                    frames.append({"timestamp_sec": round(max(0.0, t + dt), 2), "image_base64": to_jpeg_b64(img)})
            rule = kb.rule_of(code)
            violations.append({
                "type": rule["type_name"],
                "timecode_sec": t,
                "description": kb.build_description(code, "[MOCK] Кассир встаёт и уходит от стола, на столе остаются предметы"),
                "evidence_frames": frames[:3] or [],
                "type_code": code,
                "confidence": 0.77,
                "rule": {"kind": rule.get("norm_kind"), "refs": kb.refs_struct(code), "caveat": rule.get("caveat")},
                "source": "mock",
            })
    n = max(1, int(dur * 2))
    return {
        "verdict": "violation" if violations else "no_violation",
        "violations": violations,
        "timeline": {
            "t": [round(i / 2, 2) for i in range(n)],
            "people": [1 if i < n * 0.7 else 0 for i in range(n)],
            "screen_on": [1] * n,
            "phone": [0] * n,
            "drink": [0] * n,
            "bag": [0] * n,
        },
        "meta": {"duration_sec": round(dur, 2), "processing_sec": delay, "mock": True},
    }
