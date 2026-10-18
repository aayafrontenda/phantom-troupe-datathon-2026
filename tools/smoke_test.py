from __future__ import annotations

import argparse
import concurrent.futures as cf
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.schema import validate_job  # noqa: E402

LIMIT_SEC = 300


def run_one(url: str, key: str, path: Path) -> dict:
    h = {"X-API-Key": key}
    t0 = time.time()
    with httpx.Client(timeout=120) as c:
        with open(path, "rb") as f:
            r = c.post(f"{url}/api/v1/analyze", headers=h, files={"file": (path.name, f, "video/quicktime")})
        if r.status_code != 200:
            return {"video": path.name, "ok": False, "error": f"POST {r.status_code}: {r.text[:200]}"}
        job_id = r.json()["job_id"]
        while True:
            j = c.get(f"{url}/api/v1/jobs/{job_id}", headers=h).json()
            if j.get("status") != "processing":
                break
            if time.time() - t0 > LIMIT_SEC + 30:
                break
            time.sleep(2)
    sec = time.time() - t0
    errs = validate_job(j)
    ok = j.get("status") == "done" and not errs and sec <= LIMIT_SEC
    return {"video": path.name, "ok": ok, "sec": round(sec, 1), "status": j.get("status"),
            "verdict": j.get("verdict"), "n": len(j.get("violations") or []),
            "types": [v.get("type") for v in j.get("violations") or []], "schema": errs[:3], "error": j.get("error")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="*")
    ap.add_argument("--url", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--dir")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--parallel", type=int, default=5)
    a = ap.parse_args()
    paths = [Path(v) for v in a.videos]
    if a.dir:
        paths += sorted(Path(a.dir).glob("*.mov"))[: a.limit]
    if not paths:
        ap.error("укажите видео или --dir")
    url = a.url.rstrip("/")
    print(f"отправляю {len(paths)} видео параллельно ({a.parallel}) на {url}")
    with cf.ThreadPoolExecutor(a.parallel) as ex:
        results = list(ex.map(lambda p: run_one(url, a.key, p), paths))
    for r in results:
        mark = "OK " if r["ok"] else "!! "
        print(f"{mark}{r['video']:>16}  {r.get('sec', '-'):>6} с  {r.get('status')}  {r.get('verdict')}  "
              f"{r.get('n', 0)} нар.  {r.get('types') or ''}  {r.get('schema') or ''} {r.get('error') or ''}")
    bad = [r for r in results if not r["ok"]]
    print(f"\nитог: {len(results) - len(bad)}/{len(results)} OK; максимум {max(r.get('sec', 0) for r in results)} с")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
