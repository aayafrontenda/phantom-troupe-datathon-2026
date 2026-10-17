"""Service settings. Everything comes from environment variables (a repo-level .env is loaded first).

Precedence: process environment > .env file > defaults. Call `get_settings()` anywhere; tests call
`reset_settings()` after changing os.environ.
"""
from __future__ import annotations

import os
import secrets
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader: existing process variables win, empty values are ignored."""
    p = path or (REPO_DIR / ".env")
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v != "" and k not in os.environ:
            os.environ[k] = v


def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return default if v is None or v.strip() == "" else v


def _int(name: str, default: int) -> int:
    return int(float(_env(name, str(default))))


def _float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in _env(name, default).split(",") if x.strip()]


def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "-C", str(REPO_DIR), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=3)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


@dataclass
class Settings:
    # --- paths ---
    storage_dir: Path = field(default_factory=lambda: Path(_env("STORAGE_DIR", str(REPO_DIR / "storage"))).resolve())

    # --- analyzer / workers ---
    analyzer: str = field(default_factory=lambda: _env("ANALYZER", "mock"))          # mock | ml | module:callable
    worker_mode: str = field(default_factory=lambda: _env("WORKER_MODE", "process"))  # process | thread
    workers: int = field(default_factory=lambda: _int("WORKERS", 1))                  # one GPU -> one worker
    warmup: bool = field(default_factory=lambda: _bool("WARMUP", True))

    # --- deadlines (jury waits 300 s from the start of the upload) ---
    job_hard_limit_sec: float = field(default_factory=lambda: _float("JOB_HARD_LIMIT_SEC", 270))
    watchdog_grace_sec: float = field(default_factory=lambda: _float("WATCHDOG_GRACE_SEC", 8))
    worker_stall_sec: float = field(default_factory=lambda: _float("WORKER_STALL_SEC", 150))
    on_deadline: str = field(default_factory=lambda: _env("ON_DEADLINE", "partial"))  # partial | failed
    on_failure: str = field(default_factory=lambda: _env("ON_FAILURE", "partial"))    # partial | failed
    max_attempts: int = field(default_factory=lambda: _int("MAX_ATTEMPTS", 2))
    retry_on_error: bool = field(default_factory=lambda: _bool("RETRY_ON_ERROR", True))

    # --- uploads ---
    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 200))
    allowed_ext: set[str] = field(default_factory=lambda: set(_list("ALLOWED_EXT", ".mov,.mp4,.m4v")))
    video_ttl_sec: int = field(default_factory=lambda: _int("VIDEO_TTL_SEC", 3600))
    result_ttl_sec: int = field(default_factory=lambda: _int("RESULT_TTL_SEC", 0))  # 0 = keep results
    dedup: bool = field(default_factory=lambda: _bool("DEDUP", True))
    make_clips: bool = field(default_factory=lambda: _bool("MAKE_CLIPS", True))
    clip_sec: float = field(default_factory=lambda: _float("CLIP_SEC", 10))

    # --- auth ---
    api_key: str = field(default_factory=lambda: _env("API_KEY", ""))
    admin_key: str = field(default_factory=lambda: _env("ADMIN_KEY", ""))
    ui_require_key: bool = field(default_factory=lambda: _bool("UI_REQUIRE_KEY", False))
    rate_limit_per_min: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MIN", 60))
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS", "*"))

    # --- live ---
    live_fps: float = field(default_factory=lambda: _float("LIVE_FPS", 4))
    live_fps_busy: float = field(default_factory=lambda: _float("LIVE_FPS_BUSY", 1))
    camera_reconnect_sec: float = field(default_factory=lambda: _float("CAMERA_RECONNECT_SEC", 5))
    live_max_side: int = field(default_factory=lambda: _int("LIVE_MAX_SIDE", 640))

    # --- alerts ---
    alerts_config: Path = field(default_factory=lambda: Path(_env("ALERTS_CONFIG", str(REPO_DIR / "backend" / "alerts.yaml"))))
    telegram_bot_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_operator: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_OPERATOR", ""))
    telegram_chat_supervisor: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_SUPERVISOR", ""))
    alert_webhook_url: str = field(default_factory=lambda: _env("ALERT_WEBHOOK_URL", ""))
    alert_webhook_secret: str = field(default_factory=lambda: _env("ALERT_WEBHOOK_SECRET", ""))
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: _int("SMTP_PORT", 587))
    smtp_user: str = field(default_factory=lambda: _env("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: _env("SMTP_FROM", ""))
    alert_email_operator: str = field(default_factory=lambda: _env("ALERT_EMAIL_OPERATOR", ""))
    alert_email_supervisor: str = field(default_factory=lambda: _env("ALERT_EMAIL_SUPERVISOR", ""))
    public_url: str = field(default_factory=lambda: _env("PUBLIC_URL", ""))  # used in alert links

    # --- logging / misc ---
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    log_json: bool = field(default_factory=lambda: _bool("LOG_JSON", False))
    mock_delay: float = field(default_factory=lambda: _float("MOCK_DELAY", 3))
    version: str = field(default_factory=lambda: _env("APP_VERSION", "") or _git_sha())

    # ------------------------------------------------------------------
    @property
    def upload_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def results_dir(self) -> Path:
        return self.storage_dir / "results"

    @property
    def evidence_dir(self) -> Path:
        return self.storage_dir / "evidence"

    @property
    def db_path(self) -> Path:
        return self.storage_dir / "cashguard.sqlite3"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        for d in (self.storage_dir, self.upload_dir, self.results_dir, self.evidence_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolve_api_key(self) -> str:
        """Jury key: API_KEY from env, otherwise generated once and kept in storage/api_key.txt."""
        if self.api_key.strip():
            return self.api_key.strip()
        f = self.storage_dir / "api_key.txt"
        if f.exists():
            key = f.read_text(encoding="utf-8").strip()
            if key:
                return key
        self.ensure_dirs()
        key = secrets.token_urlsafe(24)
        f.write_text(key, encoding="utf-8")
        return key

    def resolve_admin_key(self) -> str:
        return self.admin_key.strip() or self.resolve_api_key()

    def safe_dict(self) -> dict:
        """Settings without secrets, for /admin/api/config."""
        hidden = {"api_key", "admin_key", "telegram_bot_token", "alert_webhook_secret", "smtp_password"}
        out = {}
        for k, v in self.__dict__.items():
            if k in hidden:
                out[k] = "***" if v else ""
            elif isinstance(v, (Path, set)):
                out[k] = sorted(v) if isinstance(v, set) else str(v)
            else:
                out[k] = v
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    s = Settings()
    s.ensure_dirs()
    return s


def reset_settings() -> None:
    get_settings.cache_clear()
