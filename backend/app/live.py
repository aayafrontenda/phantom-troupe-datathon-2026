"""Live-режим: браузер шлёт JPEG-кадры по WebSocket, сервер отвечает детекциями и алертами.

Протокол (JSON-текст):
  клиент -> {"image": "<base64 JPEG>", "t": <секунды, необязательно>}   (или бинарное сообщение = JPEG)
  сервер -> {"detections": [{group,label,score,box}], "alerts": [...новые...], "active": [коды], "ms": 35,
             "size": [w, h]}

ANALYZER=mock: детектора нет — сервер отвечает пустыми детекциями (для разработки интерфейса).
TODO (Backend): RTSP-источник (IP-камера) — отдельный поток читает cv2.VideoCapture(rtsp_url)
и шлёт клиенту те же сообщения + кадр.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

import cv2
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from . import config

log = logging.getLogger("backend.live")


def _decode(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


async def live_session(ws: WebSocket) -> None:
    await ws.accept()
    detector = None
    rules = None
    if config.ANALYZER == "ml":
        try:
            from ml.detector import get_detector
            from ml.live import LiveRules
            detector = await asyncio.to_thread(get_detector)
            rules = LiveRules()
        except Exception as e:
            await ws.send_text(json.dumps({"error": f"детектор недоступен: {e}"}, ensure_ascii=False))
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                img = _decode(msg["bytes"])
            elif msg.get("text"):
                payload = json.loads(msg["text"])
                b64 = payload.get("image", "")
                if "," in b64[:40]:
                    b64 = b64.split(",", 1)[1]  # data:image/jpeg;base64,....
                img = _decode(base64.b64decode(b64))
            else:
                continue
            if img is None:
                continue
            t0 = time.time()
            dets, alerts, active = [], [], []
            if detector is not None:
                dets = (await asyncio.to_thread(detector, [img]))[0]
                alerts = rules.update(img, dets)
                active = rules.active()
            await ws.send_text(json.dumps({
                "detections": [d.as_dict() for d in dets],
                "alerts": alerts,
                "active": active,
                "ms": int((time.time() - t0) * 1000),
                "size": [img.shape[1], img.shape[0]],
            }, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("live session error")
