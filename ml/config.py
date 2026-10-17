"""Настройки ML-пайплайна. Всё задаётся переменными окружения (см. .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
REPO_DIR = ML_DIR.parent


def load_dotenv(path: Path = REPO_DIR / ".env") -> None:
    """Минимальный загрузчик .env: переменные окружения процесса имеют приоритет."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split(" #", 1)[0].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ and v != "":
            os.environ[k] = v


load_dotenv()


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass
class Settings:
    # --- кадры ---
    sample_fps: float = field(default_factory=lambda: _f("SAMPLE_FPS", 2.0))
    det_max_side: int = field(default_factory=lambda: _i("DET_MAX_SIDE", 640))

    # --- детектор (COCO, Apache-2.0) ---
    detector_model: str = field(default_factory=lambda: os.getenv("DETECTOR_MODEL", "PekingU/rtdetr_r18vd"))
    detector_device: str = field(default_factory=lambda: os.getenv("DETECTOR_DEVICE", "auto"))  # auto|cuda|mps|cpu
    det_score: float = field(default_factory=lambda: _f("DET_SCORE", 0.45))

    # --- VLM (локально: Ollama или OpenAI-совместимый сервер, например vLLM) ---
    vlm_backend: str = field(default_factory=lambda: os.getenv("VLM_BACKEND", "ollama"))  # ollama|openai|none
    vlm_url: str = field(default_factory=lambda: os.getenv("VLM_URL", "http://127.0.0.1:11434"))
    vlm_model: str = field(default_factory=lambda: os.getenv("VLM_MODEL", "qwen3.5:4b"))
    vlm_timeout: float = field(default_factory=lambda: _f("VLM_TIMEOUT", 60))
    vlm_image_side: int = field(default_factory=lambda: _i("VLM_IMAGE_SIDE", 448))
    vlm_frames_per_call: int = field(default_factory=lambda: _i("VLM_FRAMES_PER_CALL", 5))
    vlm_window_sec: float = field(default_factory=lambda: _f("VLM_WINDOW_SEC", 6.0))
    max_vlm_calls: int = field(default_factory=lambda: _i("MAX_VLM_CALLS", 12))
    # старый проход «найди любое нарушение по чек-листу» — давал ложные на 19 из 20 нормальных видео
    vlm_generic: bool = field(default_factory=lambda: os.getenv("VLM_GENERIC", "0") == "1")
    # скан рабочего места (увеличенный фрагмент вокруг ноутбука): шаг и предел вызовов на видео
    desk_step_sec: float = field(default_factory=lambda: _f("DESK_STEP_SEC", 2.0))
    desk_max_calls: int = field(default_factory=lambda: _i("DESK_MAX_CALLS", 40))

    # --- решение ---
    min_confidence: float = field(default_factory=lambda: _f("MIN_CONFIDENCE", 0.5))
    merge_sec: float = field(default_factory=lambda: _f("MERGE_SEC", 5.0))

    # --- бюджет времени на одно видео (жюри ждёт максимум 300 с, с учётом очереди) ---
    time_budget_sec: float = field(default_factory=lambda: _f("TIME_BUDGET_SEC", 120))

    # --- выход ---
    evidence_max_side: int = field(default_factory=lambda: _i("EVIDENCE_MAX_SIDE", 640))
    evidence_jpeg_quality: int = field(default_factory=lambda: _i("EVIDENCE_JPEG_QUALITY", 85))

    kb_path: Path = field(default_factory=lambda: Path(os.getenv("KB_PATH", ML_DIR / "rules_kb.yaml")))


def get_settings() -> Settings:
    return Settings()
