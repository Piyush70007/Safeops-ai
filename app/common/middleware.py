"""Per-request correlation ID, metrics, access log and lab fault injection."""

import logging
import re
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.common.logging_setup import correlation_id_var
from app.common.metrics import LATENCY, REQUESTS

logger = logging.getLogger("access")
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
BUSINESS_PREFIXES = ("/orders", "/inventory", "/payments")
QUIET = ("/metrics", "/health/live", "/health/ready")


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, service: str, faults) -> None:
        super().__init__(app)
        self.service = service
        self.faults = faults

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        correlation_id = incoming if SAFE_ID.match(incoming) else uuid.uuid4().hex[:16]
        token = correlation_id_var.set(correlation_id)
        started = time.perf_counter()
        try:
            if request.url.path.startswith(BUSINESS_PREFIXES):
                self.faults.delay()
                if self.faults.should_fail():
                    response = JSONResponse(
                        {"detail": "injected fault", "correlation_id": correlation_id}, 500
                    )
                    logger.error("lab fault injected", extra={"path": request.url.path})
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        duration = time.perf_counter() - started
        route = route_template(request)
        REQUESTS.labels(self.service, route, request.method, str(response.status_code)).inc()
        LATENCY.labels(self.service, route).observe(duration)
        response.headers["X-Request-ID"] = correlation_id
        if request.url.path not in QUIET:
            correlation_id_var.set(correlation_id)
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "route": route,
                    "status": response.status_code,
                    "duration_ms": round(duration * 1000, 1),
                },
            )
            correlation_id_var.set("-")
        return response
