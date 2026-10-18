"""Per-frame live analysis: detector + stateful rules (ANALYZER=ml) or a motion-based stand-in (mock)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import cv2
import numpy as np

from ..config import get_settings

log = logging.getLogger("backend.live.analyzer")

_detector: Any = None
_detector_lock = threading.Lock()
_detector_error: str | None = None


def _get_detector() -> Any:
    global _detector, _detector_error
    with _detector_lock:
        if _detector is None and _detector_error is None:
            try:
                from ml.detector import get_detector
                _detector = get_detector()
            except Exception as e:
                _detector_error = f"{type(e).__name__}: {e}"
                log.error("live detector unavailable: %s", _detector_error)
        if _detector is None:
            raise RuntimeError(_detector_error or "detector not loaded")
        return _detector


class LiveSession:
    """One stateful analysis stream (a browser tab or a camera)."""

    def process(self, img: np.ndarray) -> dict:
        raise NotImplementedError

    def close(self) -> None:
        pass


class MLLiveSession(LiveSession):
    def __init__(self, busy=None):
        from ml.live import LiveRules
        self.det = _get_detector()
        # busy() -> True while jury/UI videos are being analyzed: live keeps the detector but skips VLM questions,
        # so camera sessions never queue in front of the jury at the single GPU
        self.rules = LiveRules(busy=busy)

    def process(self, img: np.ndarray) -> dict:
        with _detector_lock:
            dets = self.det([img])[0]
        alerts = self.rules.update(img, dets)
        return {"detections": [d.as_dict() for d in dets], "alerts": alerts, "active": self.rules.active()}


class MockLiveSession(LiveSession):
    """No model: background subtraction -> 'motion' boxes, so the UI has something to draw on a laptop.

    Every motion episode raises one demo finding ([MOCK], rotating over a few violation types) so the
    operator / supervisor workflow can be exercised without the model.
    """

    ON, OFF = 3, 6
    DEMO_CODES = ("T13", "T15", "T14", "T01")

    def __init__(self):
        self.bg = cv2.createBackgroundSubtractorMOG2(history=120, varThreshold=32, detectShadows=False)
        self.on = 0
        self.off = 0
        self.active = False
        self.episodes = 0
        self.code: str | None = None

    def process(self, img: np.ndarray) -> dict:
        small = resize_max_side(img, 320)
        k = img.shape[1] / small.shape[1]
        mask = self.bg.apply(small)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        h, w = small.shape[:2]
        dets = []
        for c in contours:
            x, y, bw, bh = cv2.boundingRect(c)
            if bw * bh < 0.004 * w * h:
                continue
            dets.append({"group": "motion", "label": "motion", "score": round(min(1.0, bw * bh / (0.1 * w * h)), 2),
                         "box": [round(x * k, 1), round(y * k, 1), round((x + bw) * k, 1), round((y + bh) * k, 1)]})
        alerts: list[dict] = []
        if dets:
            self.on, self.off = self.on + 1, 0
            if not self.active and self.on >= self.ON:
                self.active = True
                self.code = self.DEMO_CODES[self.episodes % len(self.DEMO_CODES)]
                self.episodes += 1
                alerts.append(self._demo_alert(self.code))
        else:
            self.off, self.on = self.off + 1, 0
            if self.active and self.off >= self.OFF:
                self.active = False
        return {"detections": dets, "alerts": alerts, "active": [self.code] if self.active and self.code else []}

    @staticmethod
    def _demo_alert(code: str) -> dict:
        try:
            from ml import kb
            rule = kb.rule_of(code)
            return {"code": code, "type": rule["type_name"], "message": "[MOCK] Движение в кадре - демонстрационная тревога без модели",
                    "norm": kb.refs_text(code), "severity": "warning", "confidence": 0.5, "ts": time.time()}
        except Exception:
            return {"code": "MOTION", "type": "Движение в кадре (mock)", "message": "Обнаружено движение",
                    "norm": None, "severity": "info", "ts": time.time()}


def new_session(busy=None) -> LiveSession:
    if get_settings().analyzer == "ml":
        return MLLiveSession(busy=busy)
    return MockLiveSession()


def draw(img: np.ndarray, detections: list[dict]) -> np.ndarray:
    out = img.copy()
    for d in detections:
        x1, y1, x2, y2 = [int(v) for v in d["box"]]
        color = (0, 0, 255) if d.get("group") in ("phone", "bag", "drink", "food") else (0, 200, 0)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        cv2.putText(out, f"{d.get('label', d.get('group'))} {d.get('score', 0):.2f}", (x1, max(12, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    return out


def encode_jpeg(img: np.ndarray, quality: int = 80) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("jpeg encode failed")
    return buf.tobytes()


def resize_max_side(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    s = max(h, w)
    if s <= max_side:
        return img
    k = max_side / s
    return cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
