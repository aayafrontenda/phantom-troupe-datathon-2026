from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ml.eval.evaluate import HERE, load_labels, video_map  # noqa: E402

DEFAULT = [2, 3, 4, 16, 17, 11, 12, 15, 20, 23, 30, 31, 40, 43, 46, 34, 37, 38]
KINDS = ("mirror", "rotate", "blackgap", "freeze", "trim")
GAP = 3.0


def _event_safe_start(label: float | None, duration: float) -> float:
    t = 0.4 * duration
    if label is not None and abs(t - label) < 5:
        t = label + 6 if label + 6 + GAP < duration else max(0.0, label - 5 - GAP)
    return t


def _rotate(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    a = math.radians(abs(angle))
    scale = max(math.cos(a) + h / w * math.sin(a), math.cos(a) + w / h * math.sin(a))
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR)


def make(src: Path, dst: Path, kind: str, label: float | None, num: int) -> float | None:
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = n / fps if n else 0.0
    t_at = _event_safe_start(label, duration)
    out = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    gap_frames = int(round(GAP * fps))
    angle = 8.0 if num % 2 else -8.0
    held = None
    i = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        t = i / fps
        i += 1
        if kind == "mirror":
            img = cv2.flip(img, 1)
        elif kind == "rotate":
            img = _rotate(img, angle)
        elif kind == "trim" and t < GAP:
            continue
        elif kind == "freeze" and t_at <= t < t_at + GAP:
            held = img if held is None else held
            img = held
        if kind == "blackgap" and i - 1 == int(t_at * fps):
            black = np.zeros_like(img)
            for _ in range(gap_frames):
                out.write(black)
        out.write(img)
    cap.release()
    out.release()
    if label is None:
        return None
    if kind == "blackgap" and label >= t_at:
        return label + GAP
    if kind == "trim":
        return label - GAP if label - GAP >= 1.0 else None
    return label


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", help="номера видео через запятую (по умолчанию - набор по всем ракурсам)")
    ap.add_argument("--kinds", default=",".join(KINDS))
    a = ap.parse_args()

    vids = video_map(Path(a.videos).expanduser())
    keep = {int(x) for x in a.only.split(",")} if a.only else set(DEFAULT)
    rows = [r for r in load_labels(HERE / "labels_typed.csv") if r["num"] in keep and r["num"] in vids]
    with open(HERE / "labels_typed.csv", encoding="utf-8") as f:
        fields = next(csv.reader(f))
    for kind in a.kinds.split(","):
        folder = Path(a.out).expanduser() / kind
        folder.mkdir(parents=True, exist_ok=True)
        out_rows = []
        for r in rows:
            src = vids[r["num"]]
            new = make(src, folder / src.name, kind, r["label_sec"], r["num"])
            row = {k: r[k] for k in fields}
            if r["label"] == "violation" and new is None:
                print(f"  {kind}: {r['video']} - нарушение вырезано, видео пропущено")
                (folder / src.name).unlink(missing_ok=True)
                continue
            row["label_sec"] = "" if new is None else f"{new:.1f}"
            out_rows.append(row)
        with open(folder / "labels.csv", "w", encoding="utf-8", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=fields)
            wr.writeheader()
            wr.writerows(out_rows)
        print(f"{kind}: {len(out_rows)} видео -> {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
