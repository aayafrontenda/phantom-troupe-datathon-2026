"""Параллельный прогон ml.eval.evaluate: видео делятся на N частей, каждая часть - свой процесс.

GPU при последовательном прогоне загружен ~30% (видео идут по одному), поэтому 3–4 процесса на одной
видеокарте дают прогон в 2–3 раза быстрее. В конце - общий отчёт из готовых результатов (без пересчёта).

    python tools/eval_parallel.py --videos ~/videos --jobs 3
    python tools/eval_parallel.py --videos ~/videos --jobs 3 --only 4,47,38,16   # только эти видео

Ollama должна принимать столько же запросов одновременно: OLLAMA_NUM_PARALLEL >= jobs / gpus.

Несколько GPU (--gpus G): на каждой своя Ollama на порту 11434 + номер GPU, например для второй:
    CUDA_VISIBLE_DEVICES=1 OLLAMA_HOST=127.0.0.1:11435 ollama serve &
Процесс i работает с GPU i % G: детектор и VLM на одной видеокарте.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ml.eval.evaluate import HERE, load_labels, video_map  # noqa: E402


def shards(nums: list[int], vids: dict[int, Path], jobs: int) -> list[list[int]]:
    """Делим по размеру файла (≈ длительности): самые длинные - первыми, каждое видео - в наименее загруженную часть."""
    parts: list[list[int]] = [[] for _ in range(jobs)]
    load = [0] * jobs
    for n in sorted(nums, key=lambda n: vids[n].stat().st_size, reverse=True):
        k = load.index(min(load))
        parts[k].append(n)
        load[k] += vids[n].stat().st_size
    return [p for p in parts if p]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", required=True)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--gpus", type=int, default=1)
    ap.add_argument("--only", help="номера видео через запятую")
    ap.add_argument("--out", default=str(HERE / "out"))
    a = ap.parse_args()

    vids = video_map(Path(a.videos).expanduser())
    nums = [r["num"] for r in load_labels(HERE / "labels_typed.csv") if r["num"] in vids]
    if a.only:
        keep = {int(x) for x in a.only.split(",")}
        nums = [n for n in nums if n in keep]
    parts = shards(nums, vids, max(1, a.jobs))

    out_dir = Path(a.out) / "pipeline"
    log_dir = Path(a.out) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    procs = []
    for i, part in enumerate(parts):
        gpu = i % max(1, a.gpus)
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        if a.gpus > 1:
            env.update(CUDA_VISIBLE_DEVICES=str(gpu), VLM_URL=f"http://127.0.0.1:{11434 + gpu}")
        cmd = [sys.executable, "-m", "ml.eval.evaluate", "--videos", a.videos, "--out", a.out,
               "--only", ",".join(map(str, part)), "--force"]
        log = open(log_dir / f"part{i + 1}.log", "w", encoding="utf-8")
        procs.append((subprocess.Popen(cmd, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT), log))
        print(f"часть {i + 1}: GPU {gpu}, видео {len(part)} -> {log.name}")

    while any(p.poll() is None for p, _ in procs):
        time.sleep(10)
        done = sum(1 for n in nums if (out_dir / f"{n}.json").exists()
                   and (out_dir / f"{n}.json").stat().st_mtime >= started)
        print(f"\r  готово {done}/{len(nums)} за {time.time() - started:.0f} с", end="", flush=True)
    print()
    for p, log in procs:
        log.close()
    failed = [i + 1 for i, (p, _) in enumerate(procs) if p.returncode != 0]
    if failed:
        print(f"!! части {failed} завершились с ошибкой - см. {log_dir}")
    print(f"все части за {time.time() - started:.0f} с\n")

    # общий отчёт: все результаты уже в кеше, ничего не пересчитывается
    cmd = [sys.executable, "-m", "ml.eval.evaluate", "--videos", a.videos, "--out", a.out]
    if a.only:
        cmd += ["--only", ",".join(map(str, nums))]
    return subprocess.call(cmd, cwd=REPO) or (1 if failed else 0)


if __name__ == "__main__":
    raise SystemExit(main())
