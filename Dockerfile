# StarShield Lite — multi-stage production image
# Default CMD runs the FastAPI server on :8000

# ---------------------------------------------------------------------------
# Stage 1: build wheels / install deps
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements-docker.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    STARSHIELD_API_HOST=0.0.0.0 \
    STARSHIELD_API_PORT=8000 \
    STARSHIELD_DB_LOG=1

# Non-root user
RUN useradd --create-home --shell /bin/bash starshield \
    && mkdir -p /app/data \
    && chown -R starshield:starshield /app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=starshield:starshield . /app

# Ensure data dir is writable for SQLite + TLE cache
VOLUME ["/app/data"]

USER starshield

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" \
    || exit 1

# Default: FastAPI
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
