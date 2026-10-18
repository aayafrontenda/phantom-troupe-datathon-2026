from __future__ import annotations

import os
import secrets
import subprocess
from dataclasses import dataclass, field
import threading
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
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
    storage_dir: Path = field(default_factory=lambda: Path(_env("STORAGE_DIR", str(REPO_DIR / "storage"))).resolve())

    analyzer: str = field(default_factory=lambda: _env("ANALYZER", "mock"))
    worker_mode: str = field(default_factory=lambda: _env("WORKER_MODE", "process"))
    workers: int = field(default_factory=lambda: _int("WORKERS", 1))
    warmup: bool = field(default_factory=lambda: _bool("WARMUP", True))

    job_hard_limit_sec: float = field(default_factory=lambda: _float("JOB_HARD_LIMIT_SEC", 270))
    watchdog_grace_sec: float = field(default_factory=lambda: _float("WATCHDOG_GRACE_SEC", 8))
    worker_stall_sec: float = field(default_factory=lambda: _float("WORKER_STALL_SEC", 150))
    min_job_budget_sec: float = field(default_factory=lambda: _float("MIN_JOB_BUDGET_SEC", 35))
    on_deadline: str = field(default_factory=lambda: _env("ON_DEADLINE", "partial"))
    on_failure: str = field(default_factory=lambda: _env("ON_FAILURE", "partial"))
    max_attempts: int = field(default_factory=lambda: _int("MAX_ATTEMPTS", 2))
    retry_on_error: bool = field(default_factory=lambda: _bool("RETRY_ON_ERROR", True))

    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 200))
    allowed_ext: set[str] = field(default_factory=lambda: set(_list("ALLOWED_EXT", ".mov,.mp4,.m4v")))
    jury_video_ttl_sec: int = field(default_factory=lambda: _int("JURY_VIDEO_TTL_SEC", 3600))
    video_retention_days: int = field(default_factory=lambda: _int("VIDEO_RETENTION_DAYS", 0))
    result_ttl_sec: int = field(default_factory=lambda: _int("RESULT_TTL_SEC", 0))
    dedup: bool = field(default_factory=lambda: _bool("DEDUP", True))
    make_clips: bool = field(default_factory=lambda: _bool("MAKE_CLIPS", True))
    clip_sec: float = field(default_factory=lambda: _float("CLIP_SEC", 10))

    api_key: str = field(default_factory=lambda: _env("API_KEY", ""))
    admin_key: str = field(default_factory=lambda: _env("ADMIN_KEY", ""))
    auth_required: bool = field(default_factory=lambda: _bool("AUTH_REQUIRED", True))
    session_ttl_sec: int = field(default_factory=lambda: _int("SESSION_TTL_SEC", 7 * 86400))
    seed_users: str = field(default_factory=lambda: _env("SEED_USERS", "admin:admin:admin:Administrator"))
    secure_cookies: bool = field(default_factory=lambda: _bool("SECURE_COOKIES", False))
    rate_limit_per_min: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MIN", 60))
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS", "*"))
    api_hosts: list[str] = field(default_factory=lambda: [h.lower() for h in _list("API_HOSTS", "")])

    live_fps: float = field(default_factory=lambda: _float("LIVE_FPS", 4))
    live_fps_busy: float = field(default_factory=lambda: _float("LIVE_FPS_BUSY", 1))
    camera_reconnect_sec: float = field(default_factory=lambda: _float("CAMERA_RECONNECT_SEC", 5))
    live_max_side: int = field(default_factory=lambda: _int("LIVE_MAX_SIDE", 640))
    live_findings: bool = field(default_factory=lambda: _bool("LIVE_FINDINGS", True))
    camera_clip_pre_sec: float = field(default_factory=lambda: _float("CAMERA_CLIP_PRE_SEC", 8))
    camera_clip_post_sec: float = field(default_factory=lambda: _float("CAMERA_CLIP_POST_SEC", 4))

    quality_base_confidence: float = field(default_factory=lambda: _float("MIN_CONFIDENCE", 0.5))
    quality_min_samples: int = field(default_factory=lambda: _int("QUALITY_MIN_SAMPLES", 10))
    quality_target_precision: float = field(default_factory=lambda: _float("QUALITY_TARGET_PRECISION", 0.75))

    alerts_config: Path = field(default_factory=lambda: Path(_env("ALERTS_CONFIG", str(REPO_DIR / "backend" / "alerts.yaml"))))
    telegram_bot_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_operator: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_OPERATOR", ""))
    telegram_chat_supervisor: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_SUPERVISOR", ""))
    telegram_poll: bool = field(default_factory=lambda: _bool("TELEGRAM_POLL", True))
    telegram_photos: bool = field(default_factory=lambda: _bool("TELEGRAM_PHOTOS", True))
    alert_webhook_url: str = field(default_factory=lambda: _env("ALERT_WEBHOOK_URL", ""))
    alert_webhook_secret: str = field(default_factory=lambda: _env("ALERT_WEBHOOK_SECRET", ""))
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: _int("SMTP_PORT", 587))
    smtp_user: str = field(default_factory=lambda: _env("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: _env("SMTP_FROM", ""))
    alert_email_operator: str = field(default_factory=lambda: _env("ALERT_EMAIL_OPERATOR", ""))
    alert_email_supervisor: str = field(default_factory=lambda: _env("ALERT_EMAIL_SUPERVISOR", ""))
    public_url: str = field(default_factory=lambda: _env("PUBLIC_URL", ""))

    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    log_json: bool = field(default_factory=lambda: _bool("LOG_JSON", False))
    mock_delay: float = field(default_factory=lambda: _float("MOCK_DELAY", 3))
    version: str = field(default_factory=lambda: _env("APP_VERSION", "") or _git_sha())

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
        path = self.storage_dir / "phantomguard.sqlite3"
        legacy = self.storage_dir / "cashguard.sqlite3"
        return legacy if legacy.exists() and not path.exists() else path

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        for d in (self.storage_dir, self.upload_dir, self.results_dir, self.evidence_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolve_api_key(self) -> str:
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
        hidden = {"api_key", "admin_key", "telegram_bot_token", "alert_webhook_secret", "smtp_password", "seed_users"}
        out = {}
        for k, v in self.__dict__.items():
            if k in hidden:
                out[k] = "***" if v else ""
            elif isinstance(v, (Path, set)):
                out[k] = sorted(v) if isinstance(v, set) else str(v)
            else:
                out[k] = v
        return out


_settings: Settings | None = None
_settings_lock = threading.Lock()


def get_settings() -> Settings:
    s = _settings
    if s is not None:
        return s
    return _build_settings()


def _build_settings() -> Settings:
    global _settings
    with _settings_lock:
        if _settings is None:
            load_dotenv()
            s = Settings()
            s.ensure_dirs()
            _settings = s
        return _settings


def reset_settings() -> None:
    global _settings
    with _settings_lock:
        _settings = None
