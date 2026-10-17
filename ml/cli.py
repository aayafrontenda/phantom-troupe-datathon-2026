"""Запуск анализа одного видео из консоли.

    python -m ml.cli data/open/videos/X-1.mov            # полный пайплайн
    python -m ml.cli data/open/videos/X-1.mov --mock     # mock
    python -m ml.cli video.mov --out result.json --no-images
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from .schema import validate_result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--no-images", action="store_true", help="не печатать base64 кадров")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if a.mock:
        from .mock import analyze_mock as analyze
    else:
        from .pipeline import analyze
    t0 = time.time()
    res = analyze(a.video, on_progress=lambda st, p: print(f"[{p:4.0%}] {st}", file=sys.stderr))
    errs = validate_result(res)
    print(f"готово за {time.time() - t0:.1f} с; схема: {'OK' if not errs else errs}", file=sys.stderr)

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
    if a.no_images:
        for v in res["violations"]:
            for fr in v["evidence_frames"]:
                fr["image_base64"] = fr["image_base64"][:24] + "…"
    print(json.dumps({k: v for k, v in res.items() if k != "timeline"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
