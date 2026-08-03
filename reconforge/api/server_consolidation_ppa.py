"""Request-scoped PostgreSQL execution for non-posting acquisition PPA evidence."""

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
from reconforge.infrastructure.postgres_consolidation_ppa import (
    PostgresConsolidationPpaError,
    PostgresConsolidationPpaRepository,
)
from reconforge.platform.common import PlatformError

T = TypeVar("T")
PpaOperation = Callable[[PostgresConsolidationPpaRepository, str], T]


def get_postgres_ppa_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the explicit server-profile PPA factory, if configured."""

    value = getattr(request.app.state, "postgres_ppa_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_ppa_enabled(request: Request) -> bool:
    """Return whether PPA persistence must use the PostgreSQL server boundary."""

    return get_postgres_ppa_factory(request) is not None


def execute_postgres_ppa(request: Request, operation: PpaOperation[T]) -> T:
    """Execute one PPA operation inside a tenant-local RLS transaction."""

    factory = get_postgres_ppa_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="consolidation_ppa_unavailable",
            message="PostgreSQL consolidation PPA persistence is not configured.",
        )
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresConsolidationPpaRepository(connection, tenant_id), tenant_id)
    except APIError:
        raise
    except PlatformError as exc:
        raise APIError(status_code=400, code="consolidation_ppa_request_invalid", message=str(exc)) from exc
    except PostgresConsolidationPpaError as exc:
        message = str(exc)
        if "not found" in message.casefold():
            raise APIError(status_code=404, code="consolidation_ppa_not_found", message=message) from exc
        if any(token in message.casefold() for token in ("conflict", "immutable", "cannot be deleted")):
            raise APIError(status_code=409, code="consolidation_ppa_conflict", message=message) from exc
        if "verification" in message.casefold() or "invalid" in message.casefold():
            raise APIError(status_code=400, code="consolidation_ppa_request_invalid", message=message) from exc
        raise APIError(
            status_code=503,
            code="consolidation_ppa_unavailable",
            message="PostgreSQL consolidation PPA persistence is temporarily unavailable.",
        ) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="consolidation_ppa_unavailable",
            message="PostgreSQL consolidation PPA persistence is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="consolidation_ppa_unavailable",
            message="PostgreSQL consolidation PPA persistence is temporarily unavailable.",
        ) from exc


__all__ = ["execute_postgres_ppa", "get_postgres_ppa_factory", "server_ppa_enabled"]
