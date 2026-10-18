from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import get_settings
from .i18n import LANGS, Translator, short_desc

log = logging.getLogger("backend.reports")
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"

_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))


def _tc(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    return f"{int(v // 60)}:{v % 60:04.1f}"


def _sha8(b64: str) -> str:
    return hashlib.sha256(b64.encode("ascii", "ignore")).hexdigest()[:8]


_env.filters["tc"] = _tc
_env.filters["shortdesc"] = short_desc
_env.filters["sha8"] = _sha8


def render_report(job: dict, result: dict, clips: dict[int, str] | None = None,
                  decisions: dict[int, str] | None = None, lang: str = "ru",
                  findings: list[dict] | None = None, names: dict[str, str] | None = None) -> str:
    s = get_settings()
    tpl = _env.get_template("report.html")
    processing = round((job.get("finished_at") or time.time()) - (job.get("request_started_at") or job["created_at"]), 1)
    result_hash = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    by_index = {int(f["violation_index"]): f for f in (findings or []) if f.get("violation_index") is not None}
    decisions = decisions or {i: f["decision"] for i, f in by_index.items() if f.get("decision")}
    n = len(result.get("violations") or [])
    reviewed = sum(1 for i in range(n) if i in decisions)
    tr = Translator(lang)
    names = names or {}
    return tpl.render(job=job, result=result, clips=clips or {}, processing_sec=processing, decisions=decisions,
                      findings=by_index, names=names, reviewed=reviewed, t=tr, lang=tr.lang, langs=LANGS,
                      service_version=s.version, result_hash=result_hash,
                      generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
                      uploaded_at=datetime.fromtimestamp(job["created_at"]).strftime("%d.%m.%Y %H:%M"))


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def clip_path(job_id: str, index: int) -> Path:
    return get_settings().evidence_dir / job_id / f"violation_{index}.mp4"


def make_clips(job: dict, result: dict) -> dict[int, Path]:
    s = get_settings()
    out: dict[int, Path] = {}
    src = job.get("upload_path")
    if not s.make_clips or not src or not Path(src).exists() or not ffmpeg_available():
        return out
    for i, v in enumerate(result.get("violations") or []):
        t = float(v.get("timecode_sec") or 0.0)
        start = max(0.0, t - s.clip_sec / 2)
        dst = clip_path(job["job_id"], i)
        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", src, "-t", f"{s.clip_sec:.2f}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-an", "-movflags", "+faststart", str(dst)]
        try:
            subprocess.run(cmd, check=True, timeout=60, capture_output=True)
            out[i] = dst
        except Exception as e:
            log.warning("job %s: clip %d failed: %s", job["job_id"], i, e)
    return out
