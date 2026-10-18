from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from .config import get_settings
from .video import resize_max_side

GROUPS = {
    "person": {"person"},
    "phone": {"cell phone"},
    "drink": {"cup", "bottle", "wine glass"},
    "food": {"sandwich", "banana", "apple", "donut", "cake", "pizza", "hot dog", "orange"},
    "bag": {"handbag", "backpack", "suitcase"},
    "laptop": {"laptop"},
    "book": {"book"},
}
LABEL2GROUP = {lbl: g for g, lbls in GROUPS.items() for lbl in lbls}


@dataclass
class Det:
    group: str
    label: str
    score: float
    box: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.box
        return (x1 + x2) / 2, (y1 + y2) / 2

    def as_dict(self) -> dict:
        return {"group": self.group, "label": self.label, "score": round(self.score, 3),
                "box": [round(v, 1) for v in self.box]}


class Detector:
    def __init__(self, model_id: str | None = None, device: str | None = None):
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection

        s = get_settings()
        self.model_id = model_id or s.detector_model
        dev = device or s.detector_device
        if dev == "auto":
            if torch.cuda.is_available():
                dev = "cuda"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                dev = "mps"
            else:
                dev = "cpu"
        self.device = dev
        self.torch = torch
        self.processor = AutoImageProcessor.from_pretrained(self.model_id)
        self.model = AutoModelForObjectDetection.from_pretrained(self.model_id).to(dev).eval()
        self.id2label = self.model.config.id2label
        self.score = s.det_score
        self.max_side = s.det_max_side
        self.lock = threading.Lock()

    def __call__(self, images_bgr: list[np.ndarray], batch_size: int = 8) -> list[list[Det]]:
        out: list[list[Det]] = []
        for i in range(0, len(images_bgr), batch_size):
            with self.lock:
                out.extend(self._batch(images_bgr[i:i + batch_size]))
        return out

    def _batch(self, images_bgr: list[np.ndarray]) -> list[list[Det]]:
        torch = self.torch
        rgb = [resize_max_side(im, self.max_side)[:, :, ::-1].copy() for im in images_bgr]
        scales = [im.shape[1] / r.shape[1] for im, r in zip(images_bgr, rgb)]
        inputs = self.processor(images=rgb, return_tensors="pt").to(self.device)
        with torch.inference_mode():
            outputs = self.model(**inputs)
        sizes = torch.tensor([r.shape[:2] for r in rgb], device=self.device)
        results = self.processor.post_process_object_detection(outputs, target_sizes=sizes, threshold=self.score)
        dets_all = []
        for res, k in zip(results, scales):
            dets = []
            for score, label, box in zip(res["scores"], res["labels"], res["boxes"]):
                name = self.id2label[int(label)]
                g = LABEL2GROUP.get(name)
                if g is None:
                    continue
                x1, y1, x2, y2 = (float(v) * k for v in box)
                dets.append(Det(g, name, float(score), (x1, y1, x2, y2)))
            dets_all.append(dets)
        return dets_all


_DETECTOR: Detector | None = None


_INIT_LOCK = threading.Lock()


def get_detector() -> Detector:
    global _DETECTOR
    with _INIT_LOCK:
        if _DETECTOR is None:
            _DETECTOR = Detector()
    return _DETECTOR
