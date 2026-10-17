"""Logging: console + rotating file (storage/server.log), optional JSON lines, request id in records."""
from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import time
from pathlib import Path

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": round(time.time(), 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def setup_logging(storage_dir: Path, level: str = "INFO", json_lines: bool = False) -> Path:
    log_file = storage_dir / "server.log"
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    fmt: logging.Formatter
    if json_lines:
        fmt = _JsonFormatter()
    else:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(_RequestIdFilter())
    root.addHandler(console)
    try:
        fh = logging.handlers.RotatingFileHandler(log_file, maxBytes=20 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.addFilter(_RequestIdFilter())
        root.addHandler(fh)
    except OSError:
        pass
    for noisy in ("uvicorn.access", "httpx", "httpcore", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_file
