"""Request-scoped PostgreSQL execution for non-posting deferred-tax evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_identity import request_tenant_id
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresTenantBoundary,
    PostgresUnavailableError,
)
from reconforge.infrastructure.postgres_consolidation_deferred_tax import (
    PostgresConsolidationDeferredTaxError,
    PostgresConsolidationDeferredTaxRepository,
)
from reconforge.platform.common import PlatformError

T = TypeVar("T")
DeferredTaxOperation = Callable[[PostgresConsolidationDeferredTaxRepository, str], T]


def get_postgres_deferred_tax_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the explicit server-profile deferred-tax factory, if configured."""

    value = getattr(request.app.state, "postgres_deferred_tax_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_deferred_tax_enabled(request: Request) -> bool:
    """Return whether deferred-tax persistence must use the PostgreSQL server boundary."""

    return get_postgres_deferred_tax_factory(request) is not None


def execute_postgres_deferred_tax(request: Request, operation: DeferredTaxOperation[T]) -> T:
    """Execute one deferred-tax operation inside a tenant-local RLS transaction."""

    factory = get_postgres_deferred_tax_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="consolidation_deferred_tax_unavailable",
            message="PostgreSQL consolidation deferred-tax persistence is not configured.",
        )
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresConsolidationDeferredTaxRepository(connection, tenant_id), tenant_id)
    except APIError:
        raise
    except PlatformError as exc:
        raise APIError(
            status_code=400,
            code="consolidation_deferred_tax_request_invalid",
            message=str(exc),
        ) from exc
    except PostgresConsolidationDeferredTaxError as exc:
        message = str(exc)
        if "not found" in message.casefold():
            raise APIError(status_code=404, code="consolidation_deferred_tax_not_found", message=message) from exc
        if any(token in message.casefold() for token in ("conflict", "immutable", "cannot be deleted")):
            raise APIError(status_code=409, code="consolidation_deferred_tax_conflict", message=message) from exc
        if "verification" in message.casefold() or "invalid" in message.casefold():
            raise APIError(
                status_code=400,
                code="consolidation_deferred_tax_request_invalid",
                message=message,
            ) from exc
        raise APIError(
            status_code=503,
            code="consolidation_deferred_tax_unavailable",
            message="PostgreSQL consolidation deferred-tax persistence is temporarily unavailable.",
        ) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="consolidation_deferred_tax_unavailable",
            message="PostgreSQL consolidation deferred-tax persistence is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="consolidation_deferred_tax_unavailable",
            message="PostgreSQL consolidation deferred-tax persistence is temporarily unavailable.",
        ) from exc


__all__ = [
    "execute_postgres_deferred_tax",
    "get_postgres_deferred_tax_factory",
    "server_deferred_tax_enabled",
]
