"""Wipe test data before a demo: every uploaded check (video, result, findings, alerts) and every camera finding.

    python tools/cleanup_demo.py --url https://<address> --key <ADMIN_KEY>            # dry run: lists what would go
    python tools/cleanup_demo.py --url https://<address> --key <ADMIN_KEY> --yes      # delete
    python tools/cleanup_demo.py --url ... --key ... --yes --keep-source jury          # keep jury uploads

Users, cameras, API keys and settings are not touched.
"""
from __future__ import annotations

import argparse
import sys

import httpx


def run(c: httpx.Client, base: str, key: str, yes: bool, keep_source: list[str], out=print) -> int:
    base = base.rstrip("/")
    h = {"X-API-Key": key}
    me = c.get(f"{base}/ui/api/auth/me", headers=h)
    if me.status_code != 200 or me.json().get("user", {}).get("role") != "admin":
        out(f"key is not admin: {me.status_code} {me.text[:120]}")
        return 1
    jobs = c.get(f"{base}/ui/api/jobs?limit=500", headers=h).json()["jobs"]
    jobs = [j for j in jobs if j.get("source") not in keep_source]
    findings = c.get(f"{base}/ui/api/findings?source=camera&limit=1000", headers=h).json()["findings"]
    out(f"{len(jobs)} checks, {len(findings)} camera findings" + ("" if yes else " (dry run, add --yes)"))
    for j in jobs:
        line = f"  check {j['job_id']}  {j.get('filename')}  {j.get('source')}  {j.get('status')}"
        if yes:
            r = c.delete(f"{base}/ui/api/jobs/{j['job_id']}", headers=h)
            line += "  -> " + ("deleted" if r.status_code == 200 else f"HTTP {r.status_code}")
        out(line)
    for f in findings:
        line = f"  finding #{f['id']}  {f.get('camera_name') or f.get('camera_id')}  {f.get('type_code')}"
        if yes:
            r = c.delete(f"{base}/ui/api/findings/{f['id']}", headers=h)
            line += "  -> " + ("deleted" if r.status_code == 200 else f"HTTP {r.status_code}")
        out(line)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--key", required=True, help="ADMIN_KEY (X-API-Key with the admin role)")
    ap.add_argument("--yes", action="store_true", help="actually delete (default: dry run)")
    ap.add_argument("--keep-source", action="append", default=[], help="job sources to keep: jury | ui | replay")
    a = ap.parse_args()
    with httpx.Client(timeout=60) as c:
        return run(c, a.url, a.key, a.yes, a.keep_source)


if __name__ == "__main__":
    sys.exit(main())
