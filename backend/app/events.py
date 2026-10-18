from __future__ import annotations

import asyncio
import fnmatch
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Sub:
    pattern: str
    sink: Any
    loop: asyncio.AbstractEventLoop | None
    created_at: float = field(default_factory=time.time)


class EventBus:
    def __init__(self, history: int = 200):
        self._subs: list[_Sub] = []
        self._lock = threading.Lock()
        self._history: list[dict] = []
        self._history_max = history

    def publish(self, topic: str, event: dict) -> None:
        msg = {"topic": topic, "ts": time.time(), **event}
        with self._lock:
            self._history.append(msg)
            if len(self._history) > self._history_max:
                self._history = self._history[-self._history_max:]
            subs = list(self._subs)
        for s in subs:
            if not fnmatch.fnmatchcase(topic, s.pattern):
                continue
            if s.loop is not None:
                try:
                    s.loop.call_soon_threadsafe(_put_async, s.sink, msg)
                except RuntimeError:
                    self.unsubscribe(s)
            else:
                try:
                    s.sink.put_nowait(msg)
                except queue.Full:
                    pass

    def subscribe_async(self, pattern: str, maxsize: int = 500) -> tuple[_Sub, asyncio.Queue]:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        sub = _Sub(pattern, q, loop)
        with self._lock:
            self._subs.append(sub)
        return sub, q

    def subscribe_sync(self, pattern: str, maxsize: int = 500) -> tuple[_Sub, queue.Queue]:
        q: queue.Queue = queue.Queue(maxsize=maxsize)
        sub = _Sub(pattern, q, None)
        with self._lock:
            self._subs.append(sub)
        return sub, q

    def unsubscribe(self, sub: _Sub) -> None:
        with self._lock:
            try:
                self._subs.remove(sub)
            except ValueError:
                pass

    def recent(self, pattern: str = "*", limit: int = 50) -> list[dict]:
        with self._lock:
            return [m for m in self._history if fnmatch.fnmatchcase(m["topic"], pattern)][-limit:]

    def subscribers(self) -> int:
        with self._lock:
            return len(self._subs)


def _put_async(q: asyncio.Queue, msg: dict) -> None:
    try:
        q.put_nowait(msg)
    except asyncio.QueueFull:
        pass
