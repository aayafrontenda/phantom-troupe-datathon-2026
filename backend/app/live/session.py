"""WebSocket live sessions.

/ui/api/live            browser sends JPEG frames (text JSON {"image": base64} or binary) -> detections + alerts
/ui/api/cameras/{id}/ws server pushes frames of a managed camera (RTSP/file) -> {"frame", "detections", ...}
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Callable

import cv2
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from .. import metrics
from ..config import get_settings
from ..events import EventBus
from . import analyzer as la

log = logging.getLogger("backend.live")


def _decode(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


async def browser_session(ws: WebSocket, on_alert: Callable[[dict], None], busy: Callable[[], bool]) -> None:
    await ws.accept()
    s = get_settings()
    metrics.SSE_CLIENTS.inc()
    session: la.LiveSession | None = None
    try:
        session = await asyncio.to_thread(la.new_session, busy)
    except Exception as e:
        await ws.send_text(json.dumps({"error": f"детектор недоступен: {e}"}, ensure_ascii=False))
    min_gap = 0.0
    last = 0.0
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                img = _decode(msg["bytes"])
            elif msg.get("text"):
                try:
                    payload = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue
                if payload.get("ping"):
                    await ws.send_text(json.dumps({"pong": time.time()}))
                    continue
                b64 = payload.get("image", "")
                if "," in b64[:40]:
                    b64 = b64.split(",", 1)[1]
                try:
                    img = _decode(base64.b64decode(b64))
                except Exception:
                    img = None
            else:
                continue
            if img is None:
                continue
            # when jury jobs are running, serve the browser at a reduced rate
            min_gap = (1.0 / s.live_fps_busy) if busy() else 0.0
            now = time.time()
            if now - last < min_gap:
                await ws.send_text(json.dumps({"skipped": True, "busy": True}))
                continue
            last = now
            t0 = time.time()
            out = {"detections": [], "alerts": [], "active": []}
            img = la.resize_max_side(img, s.live_max_side)
            if session is not None:
                try:
                    out = await asyncio.to_thread(session.process, img)
                except Exception as e:
                    log.exception("live frame failed")
                    await ws.send_text(json.dumps({"error": str(e)[:200]}))
                    continue
            ms = int((time.time() - t0) * 1000)
            metrics.LIVE_FRAMES.labels("browser").inc()
            metrics.LIVE_FRAME_SECONDS.observe(ms / 1000.0)
            await ws.send_text(json.dumps({"detections": out["detections"], "alerts": out["alerts"],
                                           "active": out["active"], "ms": ms, "busy": busy(),
                                           "size": [img.shape[1], img.shape[0]]}, ensure_ascii=False))
            for a in out["alerts"]:
                try:
                    on_alert({"source": "browser", "camera_id": "browser", "camera_name": "Камера браузера",
                              "type_code": a.get("code"), "type_name": a.get("type"), "message": a.get("message"),
                              "norm": a.get("norm"), "link": "/?view=live",
                              "evidence_b64": base64.b64encode(la.encode_jpeg(la.draw(img, out["detections"]))).decode("ascii")})
                except Exception:
                    log.exception("browser alert dispatch failed")
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("live session error")
    finally:
        metrics.SSE_CLIENTS.dec()
        if session is not None:
            session.close()


async def camera_stream(ws: WebSocket, bus: EventBus, cam_id: str, snapshot: Callable[[], bytes | None]) -> None:
    await ws.accept()
    metrics.SSE_CLIENTS.inc()
    sub, q = bus.subscribe_async(f"camera:{cam_id}")
    try:
        first = snapshot()
        if first:
            await ws.send_text(json.dumps({"type": "frame", "camera_id": cam_id,
                                           "frame": base64.b64encode(first).decode("ascii"),
                                           "detections": [], "alerts": [], "active": [], "ms": 0}))
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15)
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "keepalive", "ts": time.time()}))
                continue
            # drop backlog: only the newest frame matters
            while not q.empty():
                msg = q.get_nowait()
            await ws.send_text(json.dumps(msg, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("camera stream error")
    finally:
        bus.unsubscribe(sub)
        metrics.SSE_CLIENTS.dec()
