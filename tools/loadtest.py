from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import struct
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.schema import validate_job  # noqa: E402


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = min(len(xs) - 1, int(round((p / 100.0) * (len(xs) - 1))))
    return xs[k]


def _payload(path: Path, unique: bool) -> bytes:
    data = path.read_bytes()
    if unique:
        data += struct.pack(">I4s", 16, b"free") + os.urandom(8)
    return data


async def one_upload(client: httpx.AsyncClient, url: str, key: str, path: Path, limit: float,
                     sem: asyncio.Semaphore, unique: bool) -> dict:
    async with sem:
        t0 = time.time()
        r = await client.post(f"{url}/api/v1/analyze", headers={"X-API-Key": key},
                              files={"file": (path.name, _payload(path, unique), "video/quicktime")})
        post_sec = time.time() - t0
        if r.status_code != 200:
            return {"video": path.name, "ok": False, "post_sec": post_sec, "error": f"POST {r.status_code}: {r.text[:120]}"}
        job_id = r.json()["job_id"]
        while True:
            j = (await client.get(f"{url}/api/v1/jobs/{job_id}", headers={"X-API-Key": key})).json()
            if j.get("status") != "processing" or time.time() - t0 > limit + 30:
                break
            await asyncio.sleep(1.0)
        total = time.time() - t0
        errs = validate_job(j)
        return {"video": path.name, "ok": j.get("status") == "done" and not errs and total <= limit,
                "post_sec": post_sec, "total_sec": total, "status": j.get("status"), "verdict": j.get("verdict"),
                "n": len(j.get("violations") or []), "partial": j.get("partial", False), "schema": errs[:2],
                "error": j.get("error")}


async def run_uploads(url: str, key: str, videos: list[Path], n: int, parallel: int, limit: float,
                      unique: bool) -> list[dict]:
    sem = asyncio.Semaphore(parallel)
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
        tasks = [one_upload(client, url, key, videos[i % len(videos)], limit, sem, unique) for i in range(n)]
        return await asyncio.gather(*tasks)


def _frames_from(path: Path, max_side: int = 640, count: int = 40) -> list[bytes]:
    import cv2
    cap = cv2.VideoCapture(str(path))
    out: list[bytes] = []
    step = max(1, int((cap.get(cv2.CAP_PROP_FRAME_COUNT) or count) // count))
    i = 0
    while len(out) < count:
        ok, img = cap.read()
        if not ok:
            break
        if i % step == 0:
            h, w = img.shape[:2]
            k = max_side / max(h, w)
            if k < 1:
                img = cv2.resize(img, (int(w * k), int(h * k)))
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
            out.append(buf.tobytes())
        i += 1
    cap.release()
    return out


async def one_ws(url: str, frames: list[bytes], fps: float, seconds: float, idx: int, stats: dict) -> None:
    try:
        import websockets
    except ImportError:
        raise SystemExit("pip install websockets  (needed for --ws)")
    ws_url = url.replace("http://", "ws://").replace("https://", "wss://") + "/ui/api/live"
    gap = 1.0 / fps
    end = time.time() + seconds
    try:
        async with websockets.connect(ws_url, max_size=8 * 1024 * 1024, open_timeout=30) as ws:
            i = 0
            while time.time() < end:
                t0 = time.time()
                await ws.send(json.dumps({"image": base64.b64encode(frames[i % len(frames)]).decode()}))
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                rtt = time.time() - t0
                stats["frames"] += 1
                stats["rtt"].append(rtt)
                if "ms" in msg:
                    stats["server_ms"].append(msg["ms"])
                if msg.get("alerts"):
                    stats["alerts"] += len(msg["alerts"])
                i += 1
                await asyncio.sleep(max(0.0, gap - rtt))
    except Exception as e:
        stats["errors"] += 1
        stats["last_error"] = f"{type(e).__name__}: {e}"[:160]


async def run_ws(url: str, videos: list[Path], n: int, fps: float, seconds: float) -> dict:
    frames = _frames_from(videos[0]) if videos else []
    if not frames:
        import cv2
        import numpy as np
        img = np.full((360, 640, 3), 80, np.uint8)
        frames = [cv2.imencode(".jpg", img)[1].tobytes()]
    stats = {"frames": 0, "rtt": [], "server_ms": [], "alerts": 0, "errors": 0, "last_error": None}
    t0 = time.time()
    await asyncio.gather(*(one_ws(url, frames, fps, seconds, i, stats) for i in range(n)))
    stats["elapsed"] = time.time() - t0
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--key", default="")
    ap.add_argument("--dir")
    ap.add_argument("videos", nargs="*")
    ap.add_argument("--uploads", type=int, default=0)
    ap.add_argument("--parallel", type=int, default=10, help="max concurrent uploads in flight")
    ap.add_argument("--limit", type=float, default=300.0, help="per-video deadline the jury applies, s")
    ap.add_argument("--unique", action="store_true", help="make every upload byte-unique (bypass dedup)")
    ap.add_argument("--ws", type=int, default=0, help="number of live WebSocket sessions")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--json", help="write the summary to this file")
    a = ap.parse_args()
    url = a.url.rstrip("/")
    videos = [Path(v) for v in a.videos]
    if a.dir:
        videos += sorted(Path(a.dir).glob("*.mov"))
    summary: dict = {"url": url, "ts": time.time()}

    if a.uploads:
        if not videos:
            ap.error("--uploads needs videos (--dir or paths)")
        if not a.key:
            ap.error("--uploads needs --key")
        print(f"uploads: {a.uploads} jobs, {a.parallel} in flight, {len(videos)} distinct videos -> {url}")
        results = asyncio.run(run_uploads(url, a.key, videos, a.uploads, a.parallel, a.limit, a.unique))
        for r in results:
            mark = "OK " if r["ok"] else "!! "
            print(f"{mark}{r['video']:>14} post {r['post_sec']:5.1f}s total {r.get('total_sec', 0):6.1f}s "
                  f"{r.get('status')} {r.get('verdict')} n={r.get('n', 0)}{' PARTIAL' if r.get('partial') else ''} "
                  f"{r.get('schema') or ''} {r.get('error') or ''}")
        posts = [r["post_sec"] for r in results]
        totals = [r["total_sec"] for r in results if "total_sec" in r]
        ok = sum(1 for r in results if r["ok"])
        summary["uploads"] = {
            "n": len(results), "ok": ok, "failed": len(results) - ok,
            "post_p50": round(pct(posts, 50), 2), "post_p95": round(pct(posts, 95), 2),
            "total_p50": round(pct(totals, 50), 1), "total_p95": round(pct(totals, 95), 1),
            "total_max": round(max(totals) if totals else 0, 1),
            "partial": sum(1 for r in results if r.get("partial")),
        }
        s = summary["uploads"]
        print(f"\nuploads: {s['ok']}/{s['n']} OK | POST p50 {s['post_p50']}s p95 {s['post_p95']}s | "
              f"result p50 {s['total_p50']}s p95 {s['total_p95']}s max {s['total_max']}s | partial {s['partial']}")

    if a.ws:
        print(f"live: {a.ws} sessions x {a.fps} fps for {a.seconds}s -> {url}/ui/api/live")
        st = asyncio.run(run_ws(url, videos, a.ws, a.fps, a.seconds))
        summary["live"] = {
            "sessions": a.ws, "fps_requested": a.fps, "frames": st["frames"],
            "fps_delivered_total": round(st["frames"] / max(1e-6, st["elapsed"]), 1),
            "rtt_p50_ms": round(pct(st["rtt"], 50) * 1000), "rtt_p95_ms": round(pct(st["rtt"], 95) * 1000),
            "server_ms_p50": round(pct(st["server_ms"], 50)), "server_ms_p95": round(pct(st["server_ms"], 95)),
            "alerts": st["alerts"], "errors": st["errors"], "last_error": st["last_error"],
        }
        s = summary["live"]
        print(f"\nlive: {s['frames']} frames, {s['fps_delivered_total']} fps total "
              f"(target {a.ws * a.fps}) | RTT p50 {s['rtt_p50_ms']} ms p95 {s['rtt_p95_ms']} ms | "
              f"server p50 {s['server_ms_p50']} ms p95 {s['server_ms_p95']} ms | errors {s['errors']} {s['last_error'] or ''}")

    if a.json:
        Path(a.json).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"summary -> {a.json}")
    bad = (summary.get("uploads", {}).get("failed", 0) or 0) + (summary.get("live", {}).get("errors", 0) or 0)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
