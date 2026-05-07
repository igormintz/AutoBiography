FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/data/hf-cache \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Cache deps layer (include the `ml` extras so faster-whisper is installed in prod)
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --extra ml

# Pre-fetch the Whisper weights into HF_HOME so the running container never
# has to download multiple GB on its first request. Cached as its own layer
# so app code changes don't re-download the model.
COPY scripts/download_model.py scripts/download_model.py
RUN uv run --no-dev --extra ml python scripts/download_model.py

COPY . .

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
