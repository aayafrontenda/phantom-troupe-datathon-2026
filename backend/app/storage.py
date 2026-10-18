from __future__ import annotations

import hashlib
import logging
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile

from .config import get_settings
from .db import Database

log = logging.getLogger("backend.storage")


@dataclass
class Upload:
    path: Path
    size: int
    sha256: str
    filename: str
    ext: str
    duration_sec: float
    fps: float
    width: int
    height: int


def probe_video(path: Path) -> dict:
    import cv2
    from ml.video import ascii_path, probe
    info = probe(path)
    if info.frame_count <= 0:
        cap = cv2.VideoCapture(ascii_path(path))
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            raise ValueError("video has no decodable frames")
        info.height, info.width = int(frame.shape[0]), int(frame.shape[1])
    return {"duration_sec": float(info.duration), "fps": float(info.fps), "frame_count": info.frame_count,
            "width": info.width, "height": info.height}


def _safe_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return ext if 2 <= len(ext) <= 6 and ext[1:].isalnum() else ".mov"


async def save_upload(file: UploadFile) -> Upload:
    s = get_settings()
    name = file.filename or "video.mov"
    ext = _safe_ext(name)
    tmp = s.upload_dir / f"upload-{time.time_ns()}{ext}"
    h = hashlib.sha256()
    size = 0
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > s.max_upload_bytes:
                    raise HTTPException(status_code=413, detail=f"Файл больше {s.max_upload_mb} МБ")
                h.update(chunk)
                out.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Пустой файл")
    try:
        meta = probe_video(tmp)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        log.info("rejected upload %s: %s", name, e)
        raise HTTPException(status_code=400, detail="Не удалось прочитать видео") from None
    return Upload(path=tmp, size=size, sha256=h.hexdigest(), filename=name, ext=ext,
                  duration_sec=meta["duration_sec"], fps=meta["fps"], width=meta["width"], height=meta["height"])


def place_upload(up: Upload, job_id: str) -> Path:
    s = get_settings()
    final = s.upload_dir / f"{job_id}{up.ext}"
    shutil.move(str(up.path), str(final))
    return final


class Retention:
    def __init__(self, db: Database, interval_sec: float = 60.0):
        self.db = db
        self.interval = interval_sec
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="retention", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(3)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.run_once()
            except Exception:
                log.exception("retention pass failed")

    def run_once(self, now: float | None = None) -> int:
        s = get_settings()
        now = now or time.time()
        removed = 0
        rows = self.db.all("SELECT job_id, upload_path, finished_at, status, source FROM jobs "
                           "WHERE status IN ('done','failed') AND upload_path IS NOT NULL")
        for r in rows:
            fin = r["finished_at"] if r["finished_at"] is not None else now
            if r.get("source") == "jury":
                ttl = float(s.jury_video_ttl_sec)
            elif s.video_retention_days > 0:
                ttl = s.video_retention_days * 86400.0
            else:
                continue
            if now - fin < ttl:
                continue
            p = Path(r["upload_path"])
            if p.exists():
                try:
                    p.unlink()
                    removed += 1
                    log.info("job %s: video removed (TTL)", r["job_id"])
                except OSError:
                    log.warning("job %s: cannot remove %s", r["job_id"], p)
            clips = s.evidence_dir / r["job_id"]
            if clips.exists():
                shutil.rmtree(clips, ignore_errors=True)
            self.db.update("jobs", "job_id", r["job_id"], {"upload_path": None, "updated_at": now})
        if s.video_retention_days > 0:
            old_cam = self.db.all("SELECT id, frames_dir FROM findings WHERE source='camera' AND frames_dir IS NOT NULL "
                                  "AND created_at < ?", (now - s.video_retention_days * 86400.0,))
            for f in old_cam:
                shutil.rmtree(f["frames_dir"], ignore_errors=True)
                self.db.update("findings", "id", f["id"], {"frames_dir": None, "clip_path": None, "updated_at": now})
                removed += 1
        if s.result_ttl_sec > 0:
            old = self.db.all("SELECT job_id, result_path FROM jobs WHERE finished_at IS NOT NULL AND finished_at < ?",
                              (now - s.result_ttl_sec,))
            for r in old:
                if r["result_path"]:
                    Path(r["result_path"]).unlink(missing_ok=True)
                self.db.execute("DELETE FROM jobs WHERE job_id=?", (r["job_id"],))
                removed += 1
        for p in s.upload_dir.glob("upload-*"):
            try:
                if now - p.stat().st_mtime > 3600:
                    p.unlink()
            except OSError:
                pass
        return removed
