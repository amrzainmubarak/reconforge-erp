"""PostgreSQL tenant execution wrapper for dashboard metrics."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import Request

from reconforge.api.server_identity import get_postgres_identity_factory, request_tenant_id, server_identity_enabled
from reconforge.application.metrics import MetricsRepositoryProtocol
from reconforge.infrastructure.postgres import PostgresTenantBoundary
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

    factory = get_postgres_identity_factory(request)
    tenant_id = request_tenant_id(request)
    if factory is None:
        raise RuntimeError("PostgreSQL metrics mode requires a tenant and connection pool.")

    with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
        return operation(PostgresMetricsRepository(connection, tenant_id), tenant_id)
