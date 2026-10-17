"""Server-Sent Events helper over the event bus."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Callable

from fastapi.responses import StreamingResponse

from . import metrics
from .events import EventBus


def _frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(bus: EventBus, pattern: str, initial: list[dict], until: Callable[[dict], bool] | None,
                  keepalive: float) -> AsyncIterator[str]:
    sub, q = bus.subscribe_async(pattern)
    metrics.SSE_CLIENTS.inc()
    try:
        for ev in initial:
            yield _frame(ev.get("type", "message"), ev)
            if until and until(ev):
                return
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=keepalive)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield _frame(ev.get("type", "message"), ev)
            if until and until(ev):
                return
    finally:
        bus.unsubscribe(sub)
        metrics.SSE_CLIENTS.dec()


def sse_response(bus: EventBus, pattern: str, initial: list[dict] | None = None,
                 until: Callable[[dict], bool] | None = None, keepalive: float = 15.0) -> StreamingResponse:
    return StreamingResponse(_stream(bus, pattern, initial or [], until, keepalive), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
