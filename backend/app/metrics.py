"""Prometheus metrics (served at /metrics)."""
from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

JOBS_TOTAL = Counter("cashguard_jobs_total", "Jobs by final status", ["status", "source"])
JOB_ANALYSIS_SECONDS = Histogram("cashguard_job_analysis_seconds", "Analyzer time per job",
                                 buckets=(5, 10, 20, 30, 45, 60, 90, 120, 180, 240, 300))
JOB_TOTAL_SECONDS = Histogram("cashguard_job_total_seconds", "Upload-start to result per job",
                              buckets=(5, 10, 20, 30, 45, 60, 90, 120, 180, 240, 300))
JOB_PARTIAL_TOTAL = Counter("cashguard_jobs_partial_total", "Jobs finalized with a partial result", ["reason"])
QUEUE_DEPTH = Gauge("cashguard_queue_depth", "Jobs waiting for a worker")
WORKERS_BUSY = Gauge("cashguard_workers_busy", "Workers currently analyzing")
WORKERS_READY = Gauge("cashguard_workers_ready", "Workers ready (warm)")
UPLOAD_BYTES = Counter("cashguard_upload_bytes_total", "Bytes received in uploads")
UPLOAD_SECONDS = Histogram("cashguard_upload_seconds", "Upload request duration")
HTTP_REQUESTS = Counter("cashguard_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("cashguard_http_request_seconds", "HTTP latency", ["route"])
ALERTS_TOTAL = Counter("cashguard_alerts_total", "Alerts created", ["severity", "source"])
ALERT_DELIVERIES = Counter("cashguard_alert_deliveries_total", "Alert deliveries", ["channel", "status"])
LIVE_FRAMES = Counter("cashguard_live_frames_total", "Live frames analyzed", ["source"])
LIVE_FRAME_SECONDS = Histogram("cashguard_live_frame_seconds", "Live frame analysis time",
                               buckets=(0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2))
CAMERAS_ONLINE = Gauge("cashguard_cameras_online", "Cameras currently streaming")
SSE_CLIENTS = Gauge("cashguard_sse_clients", "Open SSE/WebSocket subscriptions")


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
