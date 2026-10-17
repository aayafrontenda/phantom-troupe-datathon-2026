"""Чтение видео и работа с кадрами (OpenCV)."""
from __future__ import annotations

import base64
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np


@dataclass
class VideoInfo:
    path: str
    fps: float
    frame_count: int
    duration: float
    width: int
    height: int


@dataclass
class Frame:
    t: float          # секунды от начала видео
    index: int        # номер кадра в исходном видео
    image: np.ndarray  # BGR


def ascii_path(path: str | Path) -> str:
    """OpenCV на Windows не открывает пути с кириллицей (например «Х-4.mov») - делаем ASCII-копию/ссылку."""
    p = str(path)
    if os.name != "nt" or p.isascii():
        return p
    tmp = Path(tempfile.gettempdir()) / "phantomguard_ascii"
    tmp.mkdir(exist_ok=True)
    dst = tmp / (hashlib.md5(p.encode("utf-8")).hexdigest()[:12] + Path(p).suffix)
    if not dst.exists():
        try:
            os.link(p, dst)
        except OSError:
            shutil.copyfile(p, dst)
    return str(dst)


def probe(path: str | Path) -> VideoInfo:
    cap = cv2.VideoCapture(ascii_path(path))
    if not cap.isOpened():
        raise ValueError(f"Не удалось открыть видео: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    duration = n / fps if n and fps else 0.0
    return VideoInfo(str(path), float(fps), n, float(duration), w, h)


def iter_frames(path: str | Path, sample_fps: float) -> Iterator[Frame]:
    """Последовательно декодирует видео и отдаёт кадры с частотой sample_fps.

    Последовательное чтение быстрее и надёжнее, чем seek по каждому кадру в .mov.
    """
    cap = cv2.VideoCapture(ascii_path(path))
    if not cap.isOpened():
        raise ValueError(f"Не удалось открыть видео: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / sample_fps)))
    idx = 0
    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            if idx % step == 0:
                ok, img = cap.retrieve()
                if ok and img is not None:
                    yield Frame(t=idx / fps, index=idx, image=img)
            idx += 1
    finally:
        cap.release()


def frame_at(path: str | Path, t: float) -> np.ndarray | None:
    cap = cv2.VideoCapture(ascii_path(path))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
        ok, img = cap.read()
        return img if ok else None
    finally:
        cap.release()


def resize_max_side(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    s = max(h, w)
    if s <= max_side:
        return img
    k = max_side / s
    return cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)


def to_jpeg_b64(img: np.ndarray, max_side: int = 640, quality: int = 85) -> str:
    img = resize_max_side(img, max_side)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("JPEG encode failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def nearest(frames: list[Frame], t: float) -> Frame:
    return min(frames, key=lambda f: abs(f.t - t))
