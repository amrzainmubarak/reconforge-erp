"""FastAPI app factory for the local REST API foundation."""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from threading import Lock
from typing import Final, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool
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
    evidence,
    exceptions,
    finance_core,
    health,
    inventory_core,
    inventory_planning,
    inventory_valuation,
    inventory_valuation_reversal,
    master_data,
    metrics,
    payables,
    receivables,
    reconciliation,
    roles,
    users,
    workflow,
)
from reconforge.api.server_identity import authenticate_server_request, server_identity_enabled
from reconforge.db import resolve_db_path
from reconforge.db.tenancy import TenantDatabaseRouter
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.infrastructure.redis import RedisConnectionFactory, RedisSettings, TenantRedisStore
from reconforge.platform.common import ServerPrincipal, server_principal_context, trusted_local_mode

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


def create_api_app(
    db_path: Path | str,
    *,
    tenant_db_root: Path | str | None = None,
    redis_url: str | None = None,
    redis_require_tls: bool = True,
    postgres_dsn: str | None = None,
    postgres_require_tls: bool = True,
) -> FastAPI:
    """Create the API with local mode or an explicit server identity profile."""

    resolved_db_path = resolve_db_path(db_path)
    if postgres_dsn is not None and tenant_db_root is None:
        raise ValueError("tenant_db_root is required when PostgreSQL server identity is enabled.")
    app = FastAPI(
        title="ReconForge Local REST API",
        version=__version__,
        description="Local/self-hosted REST API foundation for ReconForge DB-backed workflows.",
    )
    app.state.db_path = resolved_db_path
    app.state.tenant_db_router = TenantDatabaseRouter.from_root(tenant_db_root) if tenant_db_root is not None else None
    app.state.postgres_identity_factory = (
        PostgresConnectionFactory(PostgresSettings(dsn=postgres_dsn, require_tls=postgres_require_tls))
        if postgres_dsn is not None
        else None
    )
    # The bounded PostgreSQL ledger uses the same secured connection factory
    # as server identity, but remains an explicit API capability boundary.
    app.state.postgres_ledger_factory = app.state.postgres_identity_factory
    app.state.postgres_master_data_factory = app.state.postgres_identity_factory
    app.state.postgres_close_factory = app.state.postgres_identity_factory
    app.state.postgres_evidence_factory = app.state.postgres_identity_factory
    app.state.postgres_reconciliation_factory = app.state.postgres_identity_factory
    if redis_url is not None:
        redis_factory = RedisConnectionFactory(RedisSettings(url=redis_url, require_tls=redis_require_tls))
        app.state.redis_store = TenantRedisStore(redis_factory)
    else:
        app.state.redis_store = None
    app.state.login_failures = defaultdict(deque)
    app.state.login_failures_lock = Lock()

    @app.middleware("http")
    async def add_request_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        principal: ServerPrincipal | None = None
        if server_identity_enabled(request) and request.url.path not in {"/api/v1/health", "/api/v1/version", "/api/v1/auth/login"}:
            authorization = request.headers.get("authorization", "")
            scheme, separator, raw_token = authorization.partition(" ")
            if separator and scheme.casefold() == "bearer" and raw_token.strip():
                authenticated = await run_in_threadpool(authenticate_server_request, request, raw_token.strip())
                if authenticated is not None:
                    user, permissions = authenticated
                    principal = ServerPrincipal(user=user, permissions=permissions)
                    request.state.server_principal = principal
        with trusted_local_mode(False):
            if principal is None:
                response = await call_next(request)
            else:
                with server_principal_context(principal):
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
    app.include_router(evidence.router, prefix="/api/v1")
    app.include_router(reconciliation.router, prefix="/api/v1")
    app.include_router(exceptions.router, prefix="/api/v1")
    app.include_router(metrics.router, prefix="/api/v1")
    app.include_router(payables.router, prefix="/api/v1")
    app.include_router(receivables.router, prefix="/api/v1")
    app.include_router(master_data.router, prefix="/api/v1")
    app.include_router(finance_core.router, prefix="/api/v1")
    app.include_router(inventory_core.router, prefix="/api/v1")
    app.include_router(inventory_planning.router, prefix="/api/v1")
    app.include_router(inventory_valuation.router, prefix="/api/v1")
    app.include_router(inventory_valuation_reversal.router, prefix="/api/v1")
    return app
