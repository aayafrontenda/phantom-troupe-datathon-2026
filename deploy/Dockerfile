# CashGuard service image: web UI built in a Node stage, Python service with ffmpeg.
#   WITH_ML=0 (default): backend + demo analyzer, any machine (Mac, Linux, Windows), ~600 MB.
#   WITH_ML=1: + PyTorch (CUDA 12.4 wheels bring their own CUDA runtime) + detector weights baked in.
#              Needs an NVIDIA GPU at runtime (docker-compose.gpu.yml), ~6 GB.

FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

ARG WITH_ML=0
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu124
ARG DETECTOR_MODEL=PekingU/rtdetr_r18vd

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive HF_HOME=/app/models/hf

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
COPY ml/requirements-ml.txt ./ml/requirements-ml.txt
RUN pip install -r requirements.txt
RUN if [ "$WITH_ML" = "1" ]; then \
      pip install torch torchvision --index-url "$TORCH_INDEX" \
      && pip install -r ml/requirements-ml.txt huggingface_hub \
      && python -c "from huggingface_hub import snapshot_download; snapshot_download('$DETECTOR_MODEL')"; \
    fi

COPY . .
COPY --from=ui /ui/dist ./frontend/dist
RUN mkdir -p /app/storage /app/models \
    && useradd -m -u 10001 app && chown -R app:app /app/storage /app/models
USER app

ENV STORAGE_DIR=/app/storage DETECTOR_MODEL=${DETECTOR_MODEL}
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=300s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/ready >/dev/null || exit 1
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
