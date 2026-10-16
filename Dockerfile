# ==============================================================================
# MedAudit-BD: Production Container Specification
# ==============================================================================
# Lightweight, single-stage Dockerfile serving the MedAudit-BD FastAPI backend
# and static clinical decision-support single-page application at port 8000.
#
# Free-Tier Deployment Targets:
# - Render: Web Service -> Environment: Docker -> Free Instance
# - Fly.io: fly launch --image (or Dockerfile build) -> 256MB/512MB RAM
# - Hugging Face Spaces: Docker Space -> SDK: Docker -> Port: 8000
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
    PORT=8000

WORKDIR /app

# Install build dependencies if needed, then clean up apt cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy packaging configuration and install dependencies
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy application source code, web UI, and precomputed SQLite database
COPY src/ ./src/
COPY web/ ./web/
COPY data/processed/medaudit.db ./data/processed/medaudit.db

# Ensure Python discovers src packages
ENV PYTHONPATH=/app/src

# Healthcheck for container orchestrators
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/v1/health || exit 1

# Expose service port
EXPOSE 8000

# Run FastAPI via Uvicorn
CMD ["uvicorn", "medaudit.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
