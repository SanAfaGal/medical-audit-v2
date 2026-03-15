"""FastAPI application factory with lifespan and router registration."""
from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import engine

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", host=settings.host, port=settings.port, docs=settings.docs_enabled)
    yield
    await engine.dispose()
    logger.info("shutdown")


app = FastAPI(
    title="Medical Audit v2",
    version="2.0.0",
    lifespan=lifespan,
    # Swagger UI and ReDoc are only available when DOCS_ENABLED=true (dev)
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)


@app.get("/health", include_in_schema=False)
async def health() -> JSONResponse:
    """Used by Docker HEALTHCHECK and nginx upstream probes."""
    return JSONResponse({"status": "ok"})

# --- Routers ---
from app.routers.pages import router as pages_router
from app.routers.api.hospitals import router as hospitals_router
from app.routers.api.periods import router as periods_router
from app.routers.api.invoices import router as invoices_router
from app.routers.api.findings import router as findings_router
from app.routers.api.pipeline import router as pipeline_router
from app.routers.api.settings import router as settings_router
from app.routers.api.explorer import router as explorer_router

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(pages_router)
app.include_router(hospitals_router, prefix="/api")
app.include_router(periods_router, prefix="/api")
app.include_router(invoices_router, prefix="/api")
app.include_router(findings_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(explorer_router, prefix="/api")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
