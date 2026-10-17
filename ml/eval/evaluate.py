"""Оценка на обучающих видео: вердикт, пропуски, ложные срабатывания, ошибка таймкода, тип, время.

    python -m ml.eval.evaluate --videos data/open/videos               # полный пайплайн
    python -m ml.eval.evaluate --videos data/open/videos --mock        # проверить сам скрипт
    python -m ml.eval.evaluate --videos data/open/videos --only 1,2,17 --force

Результаты анализа кешируются в ml/eval/out/<номер>.json (флаг --force пересчитывает).
Разметка: ml/eval/labels_typed.csv (тип нарушения T01–T15 проставлен вручную по просмотру видео).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import time
from collections import defaultdict
from pathlib import Path

from ..schema import validate_result

HERE = Path(__file__).resolve().parent
NUM_RE = re.compile(r"(\d+)\.mov$", re.I)


def video_map(folder: Path) -> dict[int, Path]:
    """Номер видео -> путь. Имена в архиве бывают «#U0425-4.mov», «Х-4.mov» (кириллица) или «X-4.mov»."""
    out = {}
    for p in folder.iterdir():
        m = NUM_RE.search(p.name)
        if m:
            out[int(m.group(1))] = p
    return out


def load_labels(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["num"] = int(re.search(r"(\d+)$", r["video"]).group(1))
            r["label_sec"] = float(r["label_sec"]) if r["label_sec"] else None
            rows.append(r)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", required=True)
    ap.add_argument("--labels", default=str(HERE / "labels_typed.csv"))
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", help="номера видео через запятую")
    ap.add_argument("--tol", type=float, default=3.0, help="допуск по таймкоду для засчёта типа, с")
    a = ap.parse_args()

    if a.mock:
        from ..mock import analyze_mock as analyze
    else:
        from ..pipeline import analyze

    vids = video_map(Path(a.videos))
    labels = load_labels(Path(a.labels))
    if a.only:
        keep = {int(x) for x in a.only.split(",")}
        labels = [r for r in labels if r["num"] in keep]
    out_dir = Path(a.out) / ("mock" if a.mock else "pipeline")
    out_dir.mkdir(parents=True, exist_ok=True)

    report = []
    for r in labels:
        n = r["num"]
        if n not in vids:
            print(f"!! нет файла для {r['video']}")
            continue
        cache = out_dir / f"{n}.json"
        if cache.exists() and not a.force:
            res = json.loads(cache.read_text(encoding="utf-8"))
        else:
            t0 = time.time()
            res = analyze(str(vids[n]))
            res.setdefault("meta", {})["wall_sec"] = round(time.time() - t0, 1)
            cache.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")

        schema_errs = validate_result(res)
        gt_v = r["label"] == "violation"
        pr_v = res["verdict"] == "violation"
        preds = [(v["timecode_sec"], v.get("type_code", "?"), v["type"]) for v in res["violations"]]
        dt = type_ok = None
        if gt_v and preds and r["label_sec"] is not None:
            dt = min(abs(t - r["label_sec"]) for t, _, _ in preds)
            if r["type_code"] and r["type_code"] != "T99":
                type_ok = any(c == r["type_code"] and abs(t - r["label_sec"]) <= a.tol for t, c, _ in preds)
        outcome = ("TP" if pr_v else "FN") if gt_v else ("FP" if pr_v else "TN")
        row = {
            "video": r["video"], "angle": r["camera_angle"], "label": r["label"], "label_sec": r["label_sec"],
            "gt_type": r["type_code"], "outcome": outcome,
            "pred": "; ".join(f"{t:.1f}s {c}" for t, c, _ in preds),
            "dt_sec": None if dt is None else round(dt, 1), "type_ok": type_ok,
            "sec": res.get("meta", {}).get("wall_sec") or res.get("meta", {}).get("processing_sec"),
            "schema": "OK" if not schema_errs else "; ".join(schema_errs[:2]),
        }
        report.append(row)
        print(f"{row['video']:>5} {row['angle']} {outcome}  gt={r['label_sec'] or '-':>5} {r['type_code'] or '':4}"
              f" | pred: {row['pred'] or '-'} | dt={row['dt_sec']} type_ok={type_ok} | {row['sec']} s | {row['schema']}")

    if not report:
        return 1
    with open(out_dir / "report.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(report[0].keys()))
        w.writeheader()
        w.writerows(report)

    def summary(rows: list[dict], title: str) -> None:
        c = defaultdict(int)
        for x in rows:
            c[x["outcome"]] += 1
        pos, neg = c["TP"] + c["FN"], c["FP"] + c["TN"]
        dts = [x["dt_sec"] for x in rows if x["dt_sec"] is not None]
        typ = [x["type_ok"] for x in rows if x["type_ok"] is not None]
        secs = [x["sec"] for x in rows if x["sec"]]
        print(f"\n== {title}: {len(rows)} видео")
        print(f"   точность вердикта: {(c['TP'] + c['TN']) / len(rows):.0%}")
        print(f"   пропуски (FN): {c['FN']} из {pos}   ложные (FP): {c['FP']} из {neg}")
        if dts:
            print(f"   ошибка таймкода: медиана {statistics.median(dts):.1f} с, ≤2 с у {sum(d <= 2 for d in dts)}/{len(dts)}")
        if typ:
            print(f"   тип верный: {sum(typ)}/{len(typ)}")
        if secs:
            print(f"   время: среднее {statistics.mean(secs):.1f} с, максимум {max(secs):.1f} с")

    summary(report, "ВСЕ")
    for angle in sorted({x["angle"] for x in report}):
        summary([x for x in report if x["angle"] == angle], f"ракурс {angle}")
    bad = [x for x in report if x["schema"] != "OK"]
    if bad:
        print(f"\n!! нарушения схемы ТЗ в {len(bad)} ответах - см. report.csv")
    print(f"\nотчёт: {out_dir / 'report.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
