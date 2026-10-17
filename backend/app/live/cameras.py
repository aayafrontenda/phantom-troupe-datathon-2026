"""Camera manager: one reader thread per enabled camera (RTSP / HTTP / webcam index / video file loop).

Each sampled frame goes through a LiveSession; frames + detections are published on the event bus
(`camera:{id}`), alerts go to the AlertEngine. While the job queue is busy, live sampling drops to
LIVE_FPS_BUSY so jury videos keep the GPU.
"""
from __future__ import annotations

import base64
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import cv2

from .. import metrics
from ..config import get_settings
from ..db import Database, loads
from ..events import EventBus
from . import analyzer as la

log = logging.getLogger("backend.live.cameras")


@dataclass
class CameraState:
    id: str
    status: str = "starting"             # starting | online | offline | stopped
    fps_actual: float = 0.0
    frames: int = 0
    last_frame_at: float = 0.0
    last_error: str | None = None
    last_jpeg: bytes | None = None
    last_detections: list[dict] = field(default_factory=list)
    active: list[str] = field(default_factory=list)
    size: tuple[int, int] = (0, 0)
    ms: int = 0


class CameraManager:
    def __init__(self, db: Database, bus: EventBus, on_alert: Callable[[dict], None] | None = None,
                 busy: Callable[[], bool] | None = None):
        self.db = db
        self.bus = bus
        self.on_alert = on_alert or (lambda a: None)
        self.busy = busy or (lambda: False)
        self._threads: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self.states: dict[str, CameraState] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ crud
    def list(self) -> list[dict]:
        rows = self.db.all("SELECT * FROM cameras ORDER BY created_at")
        for r in rows:
            r["meta"] = loads(r.get("meta"), {})
            r["enabled"] = bool(r["enabled"])
            r["loop"] = bool(r["loop"])
            r["state"] = self.state_dict(r["id"])
        return rows

    def get(self, cam_id: str) -> dict | None:
        r = self.db.one("SELECT * FROM cameras WHERE id=?", (cam_id,))
        if r:
            r["meta"] = loads(r.get("meta"), {})
            r["enabled"] = bool(r["enabled"])
            r["loop"] = bool(r["loop"])
            r["state"] = self.state_dict(cam_id)
        return r

    def add(self, name: str, url: str, fps: float | None = None, enabled: bool = True, loop: bool = True,
            meta: dict | None = None, cam_id: str | None = None) -> dict:
        now = time.time()
        cam_id = cam_id or uuid.uuid4().hex[:8]
        self.db.insert("cameras", {"id": cam_id, "name": name, "url": url, "enabled": int(enabled),
                                   "fps": fps or get_settings().live_fps, "loop": int(loop), "meta": meta or {},
                                   "created_at": now, "updated_at": now})
        self.db.audit("camera.add", None, cam_id, {"name": name, "url": _redact(url)})
        if enabled:
            self.start_camera(cam_id)
        return self.get(cam_id)  # type: ignore[return-value]

    def update(self, cam_id: str, **fields: Any) -> dict | None:
        allowed = {k: v for k, v in fields.items() if k in ("name", "url", "fps", "enabled", "loop", "meta") and v is not None}
        if not allowed:
            return self.get(cam_id)
        allowed["updated_at"] = time.time()
        self.db.update("cameras", "id", cam_id, allowed)
        self.stop_camera(cam_id)
        cam = self.get(cam_id)
        if cam and cam["enabled"]:
            self.start_camera(cam_id)
        return cam

    def remove(self, cam_id: str) -> bool:
        self.stop_camera(cam_id)
        n = self.db.execute("DELETE FROM cameras WHERE id=?", (cam_id,))
        self.db.audit("camera.remove", None, cam_id)
        with self._lock:
            self.states.pop(cam_id, None)
        return bool(n)

    # ------------------------------------------------------------------ lifecycle
    def start_all(self) -> None:
        for r in self.db.all("SELECT id FROM cameras WHERE enabled=1"):
            self.start_camera(r["id"])

    def stop_all(self) -> None:
        for cam_id in list(self._threads):
            self.stop_camera(cam_id)

    def start_camera(self, cam_id: str) -> None:
        with self._lock:
            if cam_id in self._threads and self._threads[cam_id].is_alive():
                return
            stop = threading.Event()
            self._stops[cam_id] = stop
            self.states[cam_id] = CameraState(cam_id)
            t = threading.Thread(target=self._run, args=(cam_id, stop), name=f"camera-{cam_id}", daemon=True)
            self._threads[cam_id] = t
            t.start()

    def stop_camera(self, cam_id: str) -> None:
        with self._lock:
            stop = self._stops.pop(cam_id, None)
            t = self._threads.pop(cam_id, None)
        if stop:
            stop.set()
        if t:
            t.join(3)
        st = self.states.get(cam_id)
        if st:
            st.status = "stopped"
        self._refresh_gauge()

    def state_dict(self, cam_id: str) -> dict:
        st = self.states.get(cam_id)
        if st is None:
            return {"status": "stopped"}
        return {"status": st.status, "fps": round(st.fps_actual, 1), "frames": st.frames, "ms": st.ms,
                "last_frame_at": st.last_frame_at, "last_error": st.last_error, "active": st.active,
                "size": list(st.size)}

    def snapshot(self, cam_id: str, annotated: bool = True) -> bytes | None:
        st = self.states.get(cam_id)
        if st is None or st.last_jpeg is None:
            return None
        if not annotated or not st.last_detections:
            return st.last_jpeg
        import numpy as np
        img = cv2.imdecode(np.frombuffer(st.last_jpeg, np.uint8), cv2.IMREAD_COLOR)
        return la.encode_jpeg(la.draw(img, st.last_detections))

    def _refresh_gauge(self) -> None:
        metrics.CAMERAS_ONLINE.set(sum(1 for s in self.states.values() if s.status == "online"))

    # ------------------------------------------------------------------ reader
    def _run(self, cam_id: str, stop: threading.Event) -> None:
        s = get_settings()
        st = self.states[cam_id]
        while not stop.is_set():
            cam = self.get(cam_id)
            if cam is None or not cam["enabled"]:
                break
            src: Any = cam["url"]
            if isinstance(src, str) and src.isdigit():
                src = int(src)
            cap = cv2.VideoCapture(src)
            if not cap.isOpened():
                st.status, st.last_error = "offline", f"cannot open {_redact(str(cam['url']))}"
                self._refresh_gauge()
                stop.wait(s.camera_reconnect_sec)
                continue
            try:
                session = la.new_session()
            except Exception as e:
                st.status, st.last_error = "offline", f"analyzer: {e}"
                cap.release()
                stop.wait(s.camera_reconnect_sec)
                continue
            st.status, st.last_error = "online", None
            self._refresh_gauge()
            src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            is_file = isinstance(src, str) and not src.startswith(("rtsp://", "http://", "https://", "udp://", "tcp://"))
            next_t = 0.0
            win_t, win_n = time.time(), 0
            log.info("camera %s online (%s, %.0f fps source)", cam_id, _redact(str(cam["url"])), src_fps)
            while not stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    if is_file and cam["loop"]:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    st.last_error = "stream ended"
                    break
                if is_file:
                    time.sleep(max(0.0, 1.0 / src_fps - 0.002))  # play files in real time
                now = time.time()
                target_fps = s.live_fps_busy if self.busy() else float(cam["fps"] or s.live_fps)
                if now < next_t:
                    continue
                next_t = now + 1.0 / max(0.2, target_fps)
                t0 = time.time()
                small = la.resize_max_side(frame, s.live_max_side)
                try:
                    out = session.process(small)
                except Exception as e:
                    st.last_error = f"analysis: {e}"
                    log.exception("camera %s: frame analysis failed", cam_id)
                    continue
                ms = int((time.time() - t0) * 1000)
                jpeg = la.encode_jpeg(small)
                st.last_jpeg, st.last_detections, st.active = jpeg, out["detections"], out["active"]
                st.frames += 1
                st.last_frame_at, st.ms, st.size = now, ms, (small.shape[1], small.shape[0])
                win_n += 1
                if now - win_t >= 2.0:
                    st.fps_actual, win_t, win_n = win_n / (now - win_t), now, 0
                metrics.LIVE_FRAMES.labels("camera").inc()
                metrics.LIVE_FRAME_SECONDS.observe(ms / 1000.0)
                self.bus.publish(f"camera:{cam_id}", {
                    "type": "frame", "camera_id": cam_id, "frame": base64.b64encode(jpeg).decode("ascii"),
                    "detections": out["detections"], "alerts": out["alerts"], "active": out["active"],
                    "ms": ms, "size": [small.shape[1], small.shape[0]]})
                for a in out["alerts"]:
                    try:
                        self.on_alert({"source": "camera", "camera_id": cam_id, "camera_name": cam["name"],
                                       "type_code": a.get("code"), "type_name": a.get("type"), "message": a.get("message"),
                                       "norm": a.get("norm"), "t_sec": None, "confidence": None,
                                       "evidence_b64": base64.b64encode(la.encode_jpeg(la.draw(small, out["detections"]))).decode("ascii"),
                                       "link": f"/?view=live&camera={cam_id}"})
                    except Exception:
                        log.exception("camera %s: alert dispatch failed", cam_id)
            cap.release()
            try:
                session.close()
            except Exception:
                pass
            if stop.is_set():
                break
            st.status = "offline"
            self._refresh_gauge()
            stop.wait(s.camera_reconnect_sec)
        st.status = "stopped"
        self._refresh_gauge()


def _redact(url: str) -> str:
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return url
