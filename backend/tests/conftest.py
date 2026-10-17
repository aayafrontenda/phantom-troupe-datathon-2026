from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np
import pytest

try:  # macOS ships with a 256 soft limit; tests spawn processes, queues and SQLite connections
    import resource
    _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if _soft < 4096:
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(4096, _hard if _hard != resource.RLIM_INFINITY else 4096), _hard))
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BASE_ENV = {
    "ANALYZER": "mock", "MOCK_DELAY": "0.2", "API_KEY": "test-key", "ADMIN_KEY": "admin-key",
    "WORKER_MODE": "thread", "WORKERS": "1", "WARMUP": "0", "JOB_HARD_LIMIT_SEC": "60",
    "WATCHDOG_GRACE_SEC": "1", "WORKER_STALL_SEC": "30", "RATE_LIMIT_PER_MIN": "1000", "MAKE_CLIPS": "0",
    "LOG_LEVEL": "WARNING", "JURY_VIDEO_TTL_SEC": "3600", "AUTH_REQUIRED": "0", "LIVE_FINDINGS": "1",
    "CAMERA_CLIP_PRE_SEC": "2", "CAMERA_CLIP_POST_SEC": "0.5",
    "SEED_USERS": "admin:admin123:admin:Admin;operator:op123:operator:Operator One;supervisor:sv123:supervisor:Super Visor",
}


@contextmanager
def make_app(tmp_path: Path, **env: str):
    """Build a fresh service bound to a temporary storage dir with the given env overrides."""
    saved = dict(os.environ)
    os.environ.update(BASE_ENV)
    os.environ["STORAGE_DIR"] = str(tmp_path / "storage")
    os.environ.update(env)
    from backend.app.config import reset_settings
    reset_settings()
    from backend.app.main import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    try:
        with TestClient(app) as c:
            yield c, app.state.st
    finally:
        os.environ.clear()
        os.environ.update(saved)
        reset_settings()


@pytest.fixture
def app_factory(tmp_path):
    return lambda **env: make_app(tmp_path, **env)


@pytest.fixture(scope="session")
def video(tmp_path_factory) -> Path:
    """Synthetic 3-second clip (so the suite does not depend on the dataset)."""
    p = tmp_path_factory.mktemp("v") / "sample.mov"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 240))
    for i in range(90):
        img = np.full((240, 320, 3), 40, np.uint8)
        cv2.circle(img, (20 + i * 3, 120), 20, (0, 0, 255), -1)
        w.write(img)
    w.release()
    _violation_sized(p)
    return p


def _violation_sized(p: Path) -> None:
    """The mock analyzer reports violations only when size % 3 != 0; encoders differ by OS, so pad if needed."""
    if p.stat().st_size % 3 == 0:
        with open(p, "ab") as f:
            f.write(b"\0")


@pytest.fixture(scope="session")
def video2(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("v2") / "sample2.mov"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 240))
    for i in range(60):
        img = np.full((240, 320, 3), 90, np.uint8)
        cv2.rectangle(img, (10 + i * 2, 50), (60 + i * 2, 150), (255, 0, 0), -1)
        w.write(img)
    w.release()
    return p


def upload(client, path: Path, key: str | None = "test-key", ui: bool = False):
    url = "/ui/api/analyze" if ui else "/api/v1/analyze"
    headers = {"X-API-Key": key} if key else {}
    with open(path, "rb") as f:
        return client.post(url, headers=headers, files={"file": (path.name, f, "video/quicktime")})


def wait_done(client, job_id: str, key: str | None = "test-key", timeout: float = 30, ui: bool = False) -> dict:
    url = f"/ui/api/jobs/{job_id}" if ui else f"/api/v1/jobs/{job_id}"
    headers = {"X-API-Key": key} if key else {}
    t0 = time.time()
    while True:
        j = client.get(url, headers=headers).json()
        if j.get("status") != "processing" or time.time() - t0 > timeout:
            return j
        time.sleep(0.1)


def wait_ready(client, timeout: float = 30) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if client.get("/ready").status_code == 200:
            return
        time.sleep(0.1)
    raise AssertionError("service never became ready")


def login(client, login: str, password: str):
    r = client.post("/ui/api/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["user"]
