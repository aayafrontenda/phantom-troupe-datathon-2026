from __future__ import annotations

import os
import time
from pathlib import Path


def _frame(path: str, t: float) -> dict:
    from ml.video import frame_at, to_jpeg_b64
    img = frame_at(path, t)
    return {"timestamp_sec": t, "image_base64": to_jpeg_b64(img)}


def quick(path: str, on_progress=None, deadline=None) -> dict:
    if on_progress:
        on_progress("detection", 0.5)
    return {"verdict": "violation",
            "violations": [{"type": "Тестовое нарушение", "timecode_sec": 1.0, "description": "test",
                            "evidence_frames": [_frame(path, 1.0)], "type_code": "T02", "confidence": 0.9}],
            "meta": {"fake": "quick"}}


def slow_with_partial(path: str, on_progress=None, deadline=None) -> dict:
    on_progress("frames", 0.1)
    time.sleep(0.5)
    on_progress.partial({"verdict": "violation",
                         "violations": [{"type": "Частичное", "timecode_sec": 2.0, "description": "partial",
                                         "evidence_frames": [_frame(path, 2.0)], "type_code": "T01", "confidence": 0.6}]})
    on_progress("vlm", 0.5)
    time.sleep(60)
    return {"verdict": "no_violation", "violations": []}


def hang(path: str, on_progress=None, deadline=None) -> dict:
    time.sleep(60)
    return {"verdict": "no_violation", "violations": []}


def crash(path: str, on_progress=None, deadline=None) -> dict:
    on_progress("detection", 0.2)
    os._exit(3)


def crash_once(path: str, on_progress=None, deadline=None) -> dict:
    marker = Path(os.environ["STORAGE_DIR"]) / "crashed.marker"
    if not marker.exists():
        marker.write_text("1")
        os._exit(3)
    return quick(path, on_progress, deadline)


def raise_error(path: str, on_progress=None, deadline=None) -> dict:
    raise RuntimeError("boom")


def bad_result(path: str, on_progress=None, deadline=None) -> dict:
    f = _frame(path, 1.0)
    return {"verdict": "no_violation",
            "violations": [{"type": "", "timecode_sec": "1.25", "description": "",
                            "evidence_frames": [f, f, f, f, {"timestamp_sec": 1, "image_base64": "not-a-jpeg"}]},
                           {"type": "Без кадров", "timecode_sec": 3, "description": "x", "evidence_frames": []},
                           "garbage"]}


def slow(path: str, on_progress=None, deadline=None) -> dict:
    time.sleep(float(os.getenv("FAKE_SLOW_SEC", "1.0")))
    return quick(path, on_progress, deadline)
