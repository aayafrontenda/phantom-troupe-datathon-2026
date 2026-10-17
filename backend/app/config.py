"""Настройки сервиса из переменных окружения (.env поддерживается через deploy/run_server.*)."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from ml.config import load_dotenv

load_dotenv()

REPO_DIR = Path(__file__).resolve().parents[2]
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", REPO_DIR / "storage")).resolve()
UPLOAD_DIR = STORAGE_DIR / "uploads"
JOBS_DIR = STORAGE_DIR / "jobs"
for d in (UPLOAD_DIR, JOBS_DIR):
    d.mkdir(parents=True, exist_ok=True)

ANALYZER = os.getenv("ANALYZER", "mock")            # mock | ml
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", 200))
ALLOWED_EXT = {".mov", ".mp4", ".m4v"}
VIDEO_TTL_SEC = int(os.getenv("VIDEO_TTL_SEC", 3600))  # видео жюри не храним дольше часа (раздел 10 ТЗ)
JOB_HARD_LIMIT_SEC = float(os.getenv("JOB_HARD_LIMIT_SEC", 280))  # от момента загрузки; жюри ждёт 300 с
UI_REQUIRE_KEY = os.getenv("UI_REQUIRE_KEY", "0") == "1"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
WARMUP = os.getenv("WARMUP", "1") == "1"


def _api_key() -> str:
    key = os.getenv("API_KEY", "").strip()
    if key:
        return key
    f = STORAGE_DIR / "api_key.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(24)
    f.write_text(key, encoding="utf-8")
    return key


API_KEY = _api_key()
