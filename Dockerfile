# ==============================================================================
# MedAudit-BD: Production Container Specification
# ==============================================================================
# Lightweight, single-stage Dockerfile serving the MedAudit-BD FastAPI backend
# and static clinical decision-support single-page application.
#
# Cloud Deployment Targets:
# - Hugging Face Spaces: Docker Space -> Port 7860 (default)
# - Render: Web Service -> Environment: Docker -> Free Tier ($PORT set dynamically)
# - Fly.io: fly launch -> 256MB/512MB RAM ($PORT set dynamically)
#
# Data Licensing Notice:
# As recorded in docs/DATA_LICENSE.md, the upstream Hugging Face dataset card
# does not specify an open commercial license. This container is intended to serve
# the interactive demonstration and API. Do NOT redistribute raw CSVs or raw
# SQLite database files as standalone downloadable datasets.
# ==============================================================================

FROM python:3.11-slim AS runner

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    HF_HOME=/tmp/hf_cache

WORKDIR /app

# Install build dependencies if needed, then clean up apt cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy packaging configuration and install dependencies
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy application source code and web UI
COPY src/ ./src/
COPY web/ ./web/

# Ensure Python discovers src packages
ENV PYTHONPATH=/app/src

# Pre-bootstrap the database during docker build if network is accessible,
# and ensure /app/data and /tmp/hf_cache are writable by non-root UID 1000 (Hugging Face Spaces)
RUN mkdir -p /app/data/raw /app/data/processed /tmp/hf_cache && \
    (python -m medaudit.db.bootstrap || true) && \
    chmod -R 777 /app/data /tmp/hf_cache

# Healthcheck for container orchestrators (supporting dynamic $PORT)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-7860}/v1/health || exit 1

# Expose default Hugging Face Spaces port (7860) and standard HTTP port (8000)
EXPOSE 7860
EXPOSE 8000

# Run database bootstrap check if medaudit.db does not exist, then start FastAPI on ${PORT:-7860}
CMD ["/bin/sh", "-c", "python -m medaudit.db.bootstrap && exec uvicorn medaudit.api.main:app --host 0.0.0.0 --port ${PORT:-7860}"]

