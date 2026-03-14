# ── Stage 1: dependency builder ─────────────────────────────────────────────
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files only — changes here invalidate the layer, not app code
COPY pyproject.toml uv.lock ./

# Install production dependencies into an isolated venv (frozen = reproducible)
RUN uv sync --frozen --no-dev --no-install-project

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# System packages required at runtime
# - ghostscript + tesseract: OCR pipeline (ocrmypdf)
# - libgl1: OpenCV dependency used by some PDF libs
RUN apt-get update && apt-get install -y --no-install-recommends \
        ghostscript \
        tesseract-ocr \
        tesseract-ocr-spa \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd --no-create-home --shell /bin/false appuser

WORKDIR /app

# Pull in the pre-built virtualenv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY app     ./app
COPY core    ./core
COPY alembic ./alembic
COPY alembic.ini ./

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"
# Prevents Python from buffering stdout/stderr (important for Docker logs)
ENV PYTHONUNBUFFERED=1
# Prevents writing .pyc files into the container layer
ENV PYTHONDONTWRITEBYTECODE=1

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Health check: FastAPI exposes /health at startup
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
