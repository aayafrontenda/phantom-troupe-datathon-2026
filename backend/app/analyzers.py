from __future__ import annotations

import importlib
import logging
from typing import Any, Callable, Protocol

log = logging.getLogger("backend.analyzers")

Analyzer = Callable[..., dict]


class Progress(Protocol):
    def __call__(self, stage: str, progress: float) -> None: ...
    def partial(self, result: dict) -> None: ...


class CallbackProgress:
    def __init__(self, on_progress: Callable[[str, float], None], on_partial: Callable[[dict], None]):
        self._p = on_progress
        self._partial = on_partial

    def __call__(self, stage: str, progress: float) -> None:
        try:
            self._p(str(stage), float(progress))
        except Exception:
            log.exception("progress callback failed")

    def partial(self, result: dict) -> None:
        try:
            self._partial(dict(result))
        except Exception:
            log.exception("partial callback failed")


def resolve(name: str) -> tuple[Analyzer, Callable[[], Any] | None, str]:
    if name == "mock":
        from ml import mock
        return mock.analyze_mock, None, "mock"
    if name == "ml":
        from ml import pipeline
        warm = getattr(pipeline, "warmup", None) or _default_ml_warmup
        return pipeline.analyze, warm, _ml_version()
    if ":" in name:
        mod_name, fn_name = name.split(":", 1)
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, fn_name)
        return fn, getattr(mod, "warmup", None), f"{mod_name}:{fn_name}"
    raise ValueError(f"unknown ANALYZER={name!r} (expected mock | ml | module:function)")


def _ml_version() -> str:
    try:
        from ml.config import get_settings
        s = get_settings()
        return f"ml/{s.detector_model}/{s.vlm_backend}:{s.vlm_model}"
    except Exception:
        return "ml"


def _default_ml_warmup() -> dict:
    out: dict[str, Any] = {}
    try:
        from ml.detector import get_detector
        get_detector()
        out["detector"] = "ok"
    except Exception as e:
        out["detector"] = f"failed: {e}"
    try:
        from ml.vlm import VLMClient
        vlm = VLMClient()
        out["vlm"] = vlm.ping() if vlm.enabled else "disabled"
    except Exception as e:
        out["vlm"] = f"failed: {e}"
    return out
