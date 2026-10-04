"""Application factory. SERVICE_MODE decides what this process is:

monolith   - orders + inventory + payments in one process and one database
orders     - only the orders API; calls inventory and payments over HTTP
inventory  - only the inventory API
payments   - only the payments API
"""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from app.common import db
from app.common.config import Settings, get_settings
from app.common.errors import Conflict, DependencyUnavailable, NotFound
from app.common.faults import Faults
from app.common.logging_setup import configure_logging, correlation_id_var
from app.common.metrics import BUILD_INFO, DEPENDENCY_ERRORS
from app.common.middleware import RequestContextMiddleware
from app.services.inventory import service as inventory_service
from app.services.inventory.api import router as inventory_router
from app.services.orders.api import router as orders_router
from app.services.orders.clients import HttpClients, LocalClients
from app.services.payments.api import router as payments_router

logger = logging.getLogger("app")
DOMAINS = ("orders", "inventory", "payments")


class FaultRequest(BaseModel):
    error_rate: float | None = Field(default=None, ge=0, le=1)
    latency_ms: int | None = Field(default=None, ge=0, le=10_000)
    memory_mb: int | None = Field(default=None, ge=0, le=2048)
    cpu_seconds: int | None = Field(default=None, ge=0, le=600)


def create_app(settings: Settings | None = None, engine=None, http_clients=None) -> FastAPI:
    settings = settings or get_settings()
    owned = [d for d in DOMAINS if settings.owns(d)]
    faults = Faults()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(
            settings.service_name,
            settings.environment,
            settings.app_version,
            settings.git_sha,
            settings.log_level,
        )
        app.state.engine = engine or db.make_engine(settings.database_url)
        try:
            db.create_tables(app.state.engine, owned)
            if "inventory" in owned and settings.seed_products:
                inventory_service.seed(app.state.engine)
        except Exception as exc:  # start anyway: readiness reports the problem honestly
            logger.warning("database setup failed", extra={"reason": type(exc).__name__})
        if settings.service_mode == "monolith":
            app.state.clients = LocalClients(app.state.engine, settings.payments_limit_cents)
        elif settings.service_mode == "orders":
            app.state.clients = http_clients or HttpClients(
                httpx.Client(
                    base_url=settings.inventory_url, timeout=settings.http_timeout_seconds
                ),
                httpx.Client(base_url=settings.payments_url, timeout=settings.http_timeout_seconds),
            )
        BUILD_INFO.labels(
            settings.service_name, settings.app_version, settings.git_sha, settings.service_mode
        ).set(1)
        logger.info("started", extra={"mode": settings.service_mode, "domains": owned})
        yield

    app = FastAPI(title=f"SafeOps shop ({settings.service_name})", lifespan=lifespan)
    app.state.settings = settings
    app.state.faults = faults
    app.add_middleware(RequestContextMiddleware, service=settings.service_name, faults=faults)

    def problem(status: int, detail: str) -> JSONResponse:
        return JSONResponse(
            {"detail": detail, "correlation_id": correlation_id_var.get()}, status_code=status
        )

    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound):
        return problem(404, str(exc))

    @app.exception_handler(Conflict)
    async def conflict(_: Request, exc: Conflict):
        return problem(409, str(exc))

    @app.exception_handler(DependencyUnavailable)
    async def unavailable(_: Request, exc: DependencyUnavailable):
        DEPENDENCY_ERRORS.labels(settings.service_name, exc.dependency, exc.reason).inc()
        logger.error(
            "dependency call failed", extra={"dependency": exc.dependency, "reason": exc.reason}
        )
        return problem(503, f"{exc.dependency} temporarily unavailable")

    @app.get("/health/live", tags=["health"])
    def live() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready(request: Request):
        try:
            db.ping(request.app.state.engine)
        except DependencyUnavailable as exc:
            return JSONResponse({"status": "not_ready", "database": exc.reason}, status_code=503)
        return {"status": "ready", "database": "ok"}

    @app.get("/version", tags=["health"])
    def version() -> dict:
        return {
            "service": settings.service_name,
            "mode": settings.service_mode,
            "version": settings.app_version,
            "git_sha": settings.git_sha,
        }

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/faults", tags=["lab"])
    def get_faults() -> dict:
        _require_faults(settings)
        return faults.snapshot()

    @app.post("/faults", tags=["lab"])
    def set_faults(body: FaultRequest) -> dict:
        _require_faults(settings)
        logger.warning("lab fault configured", extra=body.model_dump(exclude_none=True))
        return faults.configure(**body.model_dump())

    @app.delete("/faults", tags=["lab"])
    def reset_faults() -> dict:
        _require_faults(settings)
        return faults.reset()

    for domain, router in (
        ("orders", orders_router),
        ("inventory", inventory_router),
        ("payments", payments_router),
    ):
        if domain in owned:
            app.include_router(router)
    return app


def _require_faults(settings: Settings) -> None:
    if not settings.faults_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


def build() -> FastAPI:
    """Entry point for uvicorn: uvicorn --factory app.main:build"""
    return create_app()
