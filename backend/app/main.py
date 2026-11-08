"""TestPilot AI — FastAPI application entry point.

This process serves the REST API only. It never executes repository code:
long-running work (imports, analysis, generation, execution, reports) is queued
and processed by the separate worker (``python -m app.worker``).
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import models  # noqa: F401  (register models)
from app.ai.provider import get_provider
from app.api import analytics, auth, collab, github, projects, quality, runs
from app.core.config import settings
from app.core.logging import configure_logging
from app.database.session import Base, SessionLocal, engine
from app.execution.providers import get_execution_provider
from app.models import Job

configure_logging()
log = logging.getLogger("testpilot")
VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_for_runtime()
    if settings.auto_create_tables and settings.is_sqlite:
        Base.metadata.create_all(engine)
    settings.storage_path()
    log.info("TestPilot API starting (env=%s, execution=%s, ai=%s)", settings.environment,
             settings.execution_provider, settings.ai_provider)
    stop = threading.Event()
    thread = None
    if settings.run_worker_in_api:  # validate_for_runtime guarantees execution is disabled here
        from app.worker import run_loop

        thread = threading.Thread(target=run_loop, args=(stop, "api-embedded"), daemon=True, name="embedded-worker")
        thread.start()
        log.info("Embedded worker thread started (execution disabled; no repository code runs in this process)")
    yield
    stop.set()
    if thread:
        thread.join(timeout=30)
    engine.dispose()


app = FastAPI(
    title="TestPilot AI API",
    version=VERSION,
    description="Repository analysis, static analysis, test generation, isolated test execution and QA reporting.",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,  # bearer tokens, no cookies
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    return JSONResponse({"error": {"status": exc.status_code, "message": exc.detail}}, status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(x) for x in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse({"error": {"status": 422, "message": "Validation failed", "details": errors}}, status_code=422)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse({"error": {"status": 500, "message": "Internal server error"}}, status_code=500)


for r in (auth.router, auth.ws_router, github.router, projects.router, projects.jobs_router, quality.router, runs.router,
          collab.router, analytics.router):
    app.include_router(r)


@app.get("/health", tags=["system"])
def health():
    """Liveness: the process is up. Does not touch dependencies."""
    return {"status": "ok", "version": VERSION}


@app.get("/health/ready", tags=["system"])
def ready():
    """Readiness: database reachable. Never runs analysis or execution."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "unavailable", "database": "unreachable"}, status_code=503)
    return {"status": "ready", "database": "ok"}


@app.get("/api/system/capabilities", tags=["system"])
def capabilities():
    provider = get_execution_provider()
    ok, reason = provider.availability()
    with SessionLocal() as db:
        queued = db.scalar(select(func.count()).select_from(Job).where(Job.status == "queued")) or 0
        stale = db.scalar(select(func.max(Job.created_at)).where(Job.status == "queued"))
    ai = get_provider()
    return {
        "version": VERSION,
        "environment": settings.environment,
        "ai": {"configured": ai.available, "provider": settings.ai_provider if ai.available else None,
               "model": settings.ai_model if ai.available else None},
        "github": {"oauth_configured": settings.github_oauth_configured, "public_repositories": True},
        "execution": {"provider": provider.name, "available": ok, "reason": reason, "isolation": provider.isolation},
        "demo_mode": settings.demo_mode_enabled,
        "queue": {"queued_jobs": queued, "oldest_queued_at": stale.isoformat() if stale else None},
        "limits": {"max_repository_size_mb": settings.max_repository_size_mb, "execution_timeout": settings.execution_timeout},
    }
