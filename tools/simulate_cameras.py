"""Register N simulated cameras that loop videos from a folder (file-backed sources, no RTSP server needed).

The service reads each file in real time, runs the live analyzer and publishes frames/alerts exactly as it
would for an RTSP camera. Use it for the live dashboard demo and for the camera stress test.

  python tools/simulate_cameras.py --url http://127.0.0.1:8000 --key $ADMIN_KEY --dir data/open/videos --count 20
  python tools/simulate_cameras.py --url http://127.0.0.1:8000 --key $ADMIN_KEY --remove   # delete sim-* cameras

Paths must be readable by the server process (same machine or a shared mount).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--key", required=True, help="admin key (ADMIN_KEY or API_KEY)")
    ap.add_argument("--dir", help="folder with .mov files")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--prefix", default="sim")
    ap.add_argument("--remove", action="store_true", help="remove cameras with the prefix instead of adding")
    a = ap.parse_args()
    url = a.url.rstrip("/")
    h = {"X-API-Key": a.key}
    with httpx.Client(timeout=30) as c:
        if a.remove:
            cams = c.get(f"{url}/ui/api/cameras", headers=h).json()["cameras"]
            n = 0
            for cam in cams:
                if cam["id"].startswith(a.prefix + "-"):
                    c.delete(f"{url}/ui/api/cameras/{cam['id']}", headers=h)
                    n += 1
            print(f"removed {n} camera(s)")
            return 0
        if not a.dir:
            ap.error("--dir is required")
        videos = sorted(Path(a.dir).resolve().glob("*.mov"))
        if not videos:
            print("no .mov files found", file=sys.stderr)
            return 1
        added = 0
        for i in range(a.count):
            v = videos[i % len(videos)]
            cam_id = f"{a.prefix}-{i + 1:03d}"
            r = c.post(f"{url}/ui/api/cameras", headers=h,
                       json={"id": cam_id, "name": f"Касса {i + 1} ({v.stem})", "url": str(v), "fps": a.fps, "loop": True})
            if r.status_code == 201:
                added += 1
            elif r.status_code == 409:
                print(f"{cam_id}: already exists")
            else:
                print(f"{cam_id}: {r.status_code} {r.text[:120]}", file=sys.stderr)
        print(f"added {added} camera(s); open {url}/live.html or GET {url}/ui/api/cameras")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
