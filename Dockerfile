# ── Stage 1: builder (ligero, solo para el target api) ────────────────────────
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files only — changes here invalidate the layer, not app code
COPY pyproject.toml uv.lock ./

# Install production dependencies into an isolated venv (frozen = reproducible)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ── Stage 2: api — sin OCR ni Playwright (~350 MB) ────────────────────────────
FROM python:3.11-slim AS api

# BuildKit cache mount: apt no se re-descarga entre rebuilds cuando solo cambia el código
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd --no-create-home --shell /bin/false appuser

WORKDIR /app

# Pull in the pre-built virtualenv from builder
# Mismo Python 3.11 → ABI compatible, sin riesgo de C-extension mismatch
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

# ── Stage 3: full — jbarlow83/ocrmypdf (Ghostscript + Tesseract ya incluidos) ──
# Imagen oficial mantenida por el autor de ocrmypdf (James Barlow).
# Incluye: ghostscript, tesseract-ocr, tesseract-ocr-spa, libgl1 — sin apt manual.
FROM jbarlow83/ocrmypdf AS full

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

# uv sync corre dentro de esta imagen → el venv usa el Python de ocrmypdf.
# Evita incompatibilidad de ABI si la imagen base usa Python 3.12 en vez de 3.11.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY app     ./app
COPY core    ./core
COPY alembic ./alembic
COPY alembic.ini ./

# Solo Chromium — Firefox y WebKit no son necesarios (~280 MB menos que playwright install)
# --with-deps instala las librerías OS que Chromium necesita en Debian/Ubuntu
RUN /app/.venv/bin/python -m playwright install chromium --with-deps \
    && rm -rf /root/.cache/ms-playwright/.links

# Non-root user for security
RUN useradd --no-create-home --shell /bin/false appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# jbarlow83/ocrmypdf define ENTRYPOINT ["ocrmypdf"] — lo reseteamos para que
# CMD ejecute uvicorn y no se pase como argumento a ocrmypdf
ENTRYPOINT []
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
