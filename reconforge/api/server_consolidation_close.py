"""Request-scoped PostgreSQL consolidation-close operations for server mode."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_identity import request_execution_scope
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresTenantBoundary,
    PostgresUnavailableError,
)
from reconforge.infrastructure.postgres_consolidation_close import PostgresConsolidationCloseRepository
from reconforge.platform.common import PlatformError

T = TypeVar("T")
ConsolidationCloseOperation = Callable[[PostgresConsolidationCloseRepository, str], T]


def get_postgres_consolidation_close_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured PostgreSQL consolidation-close factory."""

    value = getattr(request.app.state, "postgres_consolidation_close_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_consolidation_close_enabled(request: Request) -> bool:
    """Return whether consolidation-close routes must use PostgreSQL."""

    return get_postgres_consolidation_close_factory(request) is not None


def execute_postgres_consolidation_close(
    request: Request, operation: ConsolidationCloseOperation[T]
) -> T:
    """Execute one consolidation-close operation in a hierarchy-scoped transaction."""

    factory = get_postgres_consolidation_close_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="consolidation_close_backend_not_configured",
            message="Server consolidation-close backend is not configured.",
        )
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            return operation(
                PostgresConsolidationCloseRepository(
                    connection,
                    scope.tenant_id,
                    organization_id=scope.organization_id,
                    workspace_id=scope.workspace_id,
                    legal_entity_id=scope.legal_entity_id,
                ),
                scope.tenant_id,
            )
    except APIError:
        raise
    except PlatformError as exc:
        message = str(exc)
        lowered = message.casefold()
        if "workspace scope" in lowered:
            raise APIError(status_code=403, code="workspace_scope_denied", message=message) from exc
        if "not found" in lowered:
            raise APIError(status_code=404, code="consolidation_close_not_found", message=message) from exc
        if any(token in lowered for token in ("conflict", "changed concurrently", "immutable")):
            raise APIError(status_code=409, code="consolidation_close_conflict", message=message) from exc
        raise APIError(status_code=400, code="consolidation_close_request_invalid", message=message) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="consolidation_close_unavailable",
            message="PostgreSQL consolidation close is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="consolidation_close_unavailable",
            message="PostgreSQL consolidation close is temporarily unavailable.",
        ) from exc


__all__ = [
    "execute_postgres_consolidation_close",
    "get_postgres_consolidation_close_factory",
    "server_consolidation_close_enabled",
]
