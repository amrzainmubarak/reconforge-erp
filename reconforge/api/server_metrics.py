"""PostgreSQL tenant execution wrapper for dashboard metrics."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import Request

from reconforge.api.server_identity import server_identity_enabled
from reconforge.application.metrics import MetricsRepositoryProtocol
from reconforge.infrastructure.postgres_metrics import PostgresMetricsRepository

T = TypeVar("T")


def server_metrics_enabled(request: Request) -> bool:
    """Return True if the API is operating in multi-tenant metrics mode."""
    return server_identity_enabled(request)


def execute_postgres_metrics(
    request: Request,
    operation: Callable[[MetricsRepositoryProtocol, str], T],
) -> T:
    """Execute a metrics application service operation against the tenant's PostgreSQL database."""

    tenant_id = request.headers.get("x-reconforge-tenant", "")
    connection = getattr(request.app.state, "postgres_pool", None)
    if not tenant_id or connection is None:
        raise RuntimeError("PostgreSQL metrics mode requires a tenant and connection pool.")

    repository = PostgresMetricsRepository(connection, tenant_id)
    return operation(repository, tenant_id)
