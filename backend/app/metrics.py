from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

JOBS_TOTAL = Counter("phantomguard_jobs_total", "Jobs by final status", ["status", "source"])
JOB_ANALYSIS_SECONDS = Histogram("phantomguard_job_analysis_seconds", "Analyzer time per job",
                                 buckets=(5, 10, 20, 30, 45, 60, 90, 120, 180, 240, 300))
JOB_TOTAL_SECONDS = Histogram("phantomguard_job_total_seconds", "Upload-start to result per job",
                              buckets=(5, 10, 20, 30, 45, 60, 90, 120, 180, 240, 300))
JOB_PARTIAL_TOTAL = Counter("phantomguard_jobs_partial_total", "Jobs finalized with a partial result", ["reason"])
QUEUE_DEPTH = Gauge("phantomguard_queue_depth", "Jobs waiting for a worker")
WORKERS_BUSY = Gauge("phantomguard_workers_busy", "Workers currently analyzing")
WORKERS_READY = Gauge("phantomguard_workers_ready", "Workers ready (warm)")
UPLOAD_BYTES = Counter("phantomguard_upload_bytes_total", "Bytes received in uploads")
UPLOAD_SECONDS = Histogram("phantomguard_upload_seconds", "Upload request duration")
HTTP_REQUESTS = Counter("phantomguard_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("phantomguard_http_request_seconds", "HTTP latency", ["route"])
ALERTS_TOTAL = Counter("phantomguard_alerts_total", "Alerts created", ["severity", "source"])
ALERT_DELIVERIES = Counter("phantomguard_alert_deliveries_total", "Alert deliveries", ["channel", "status"])
LIVE_FRAMES = Counter("phantomguard_live_frames_total", "Live frames analyzed", ["source"])
LIVE_FRAME_SECONDS = Histogram("phantomguard_live_frame_seconds", "Live frame analysis time",
                               buckets=(0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2))
CAMERAS_ONLINE = Gauge("phantomguard_cameras_online", "Cameras currently streaming")
SSE_CLIENTS = Gauge("phantomguard_sse_clients", "Open SSE/WebSocket subscriptions")


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
