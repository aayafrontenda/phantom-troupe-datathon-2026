"""Тесты API (mock-анализатор). Запуск из корня репозитория:  pytest -q"""
from __future__ import annotations

import importlib
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("storage")
    os.environ.update(STORAGE_DIR=str(tmp), API_KEY="test-key", ANALYZER="mock", MOCK_DELAY="0.2")
    from fastapi.testclient import TestClient
    import backend.app.config as cfg
    importlib.reload(cfg)
    import backend.app.jobs as jobs
    importlib.reload(jobs)
    import backend.app.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(scope="module")
def video(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("v") / "sample.mov"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 240))
    for i in range(90):
        img = np.full((240, 320, 3), 40, np.uint8)
        cv2.circle(img, (20 + i * 3, 120), 20, (0, 0, 255), -1)
        w.write(img)
    w.release()
    return p


def test_requires_key(client, video):
    with open(video, "rb") as f:
        r = client.post("/api/v1/analyze", files={"file": ("sample.mov", f, "video/quicktime")})
    assert r.status_code == 401
    r = client.get("/api/v1/jobs/whatever", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_rejects_non_video(client):
    r = client.post("/api/v1/analyze", headers={"X-API-Key": "test-key"},
                    files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_full_flow(client, video):
    from ml.schema import validate_job
    with open(video, "rb") as f:
        r = client.post("/api/v1/analyze", headers={"X-API-Key": "test-key"},
                        files={"file": ("sample.mov", f, "video/quicktime")})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    for _ in range(100):
        j = client.get(f"/api/v1/jobs/{job_id}", headers={"X-API-Key": "test-key"}).json()
        if j["status"] != "processing":
            break
        time.sleep(0.1)
    assert j["status"] == "done", j
    assert validate_job(j) == []
    assert list(j)[:4] == ["job_id", "status", "verdict", "violations"]


def test_ui_routes_open(client, video):
    with open(video, "rb") as f:
        r = client.post("/ui/api/analyze", files={"file": ("sample.mov", f, "video/quicktime")})
    assert r.status_code == 200
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/").status_code == 200
    info = client.get("/ui/api/info").json()
    assert len(info["types"]) >= 15
