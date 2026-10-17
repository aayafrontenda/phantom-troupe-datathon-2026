# CashGuard service image. Default build = CPU (mock or ml-on-cpu). For NVIDIA GPU pass
#   --build-arg BASE=nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 --build-arg WITH_ML=1
ARG BASE=python:3.11-slim
FROM ${BASE}
ARG WITH_ML=0
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 ca-certificates \
    && (command -v python3 >/dev/null || apt-get install -y --no-install-recommends python3 python3-pip python3-venv) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ml/requirements-ml.txt ./
RUN python3 -m pip install --upgrade pip && python3 -m pip install -r requirements.txt \
    && if [ "$WITH_ML" = "1" ]; then python3 -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124 \
         && python3 -m pip install -r requirements-ml.txt; fi

COPY . .
RUN mkdir -p /app/storage && useradd -m -u 10001 app && chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=4).status==200 else 1)"
CMD ["python3", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
