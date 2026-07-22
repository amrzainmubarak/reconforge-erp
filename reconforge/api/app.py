"""FastAPI app factory for the local REST API foundation."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast
from typing import Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from reconforge import __version__
from reconforge.api.errors import (
    APIError,
    api_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from reconforge.api.routes import (
    accounts,
    audit,
    auth,
    close,
    exceptions,
    finance_core,
    health,
    inventory_core,
    inventory_planning,
    inventory_valuation,
    inventory_valuation_reversal,
    master_data,
    metrics,
    roles,
    users,
    workflow,
)
from reconforge.db import resolve_db_path

ExceptionHandler = Callable[[Request, Exception], Response | Awaitable[Response]]

SECURITY_RESPONSE_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "accelerometer=(), ambient-light-sensor=(), battery=(), camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-Permitted-Cross-Domain-Policies": "none",
    "X-XSS-Protection": "0",
}


def create_api_app(db_path: Path | str) -> FastAPI:
    """Create the local/self-hosted ReconForge REST API app."""

    resolved_db_path = resolve_db_path(db_path)
    app = FastAPI(
        title="ReconForge Local REST API",
        version=__version__,
        description="Local/self-hosted REST API foundation for ReconForge DB-backed workflows.",
    )
    app.state.db_path = resolved_db_path

    @app.middleware("http")
    async def add_request_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_RESPONSE_HEADERS.items():
            response.headers.setdefault(header, value)
        response.headers.setdefault("Server", "reconforge-api")
        return response

    app.add_exception_handler(APIError, cast(ExceptionHandler, api_error_handler))
    app.add_exception_handler(StarletteHTTPException, cast(ExceptionHandler, http_error_handler))
    app.add_exception_handler(RequestValidationError, cast(ExceptionHandler, validation_error_handler))
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(roles.router, prefix="/api/v1")
    app.include_router(audit.router, prefix="/api/v1")
    app.include_router(workflow.router, prefix="/api/v1")
    app.include_router(accounts.router, prefix="/api/v1")
    app.include_router(close.router, prefix="/api/v1")
    app.include_router(exceptions.router, prefix="/api/v1")
    app.include_router(metrics.router, prefix="/api/v1")
    app.include_router(master_data.router, prefix="/api/v1")
    app.include_router(finance_core.router, prefix="/api/v1")
    app.include_router(inventory_core.router, prefix="/api/v1")
    app.include_router(inventory_planning.router, prefix="/api/v1")
    app.include_router(inventory_valuation.router, prefix="/api/v1")
    app.include_router(inventory_valuation_reversal.router, prefix="/api/v1")
    return app
