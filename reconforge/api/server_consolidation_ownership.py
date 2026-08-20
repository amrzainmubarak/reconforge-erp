"""Request-scoped PostgreSQL consolidation-ownership operations."""

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
from reconforge.infrastructure.postgres_consolidation_ownership import (
    PostgresConsolidationOwnershipError,
    PostgresConsolidationOwnershipRepository,
)
from reconforge.platform.common import PlatformError

T = TypeVar("T")
ConsolidationOwnershipOperation = Callable[[PostgresConsolidationOwnershipRepository, str], T]


def get_postgres_consolidation_ownership_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured PostgreSQL consolidation-ownership factory."""

    value = getattr(request.app.state, "postgres_consolidation_ownership_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_consolidation_ownership_enabled(request: Request) -> bool:
    """Return whether ownership routes must use PostgreSQL."""

    return get_postgres_consolidation_ownership_factory(request) is not None


def execute_postgres_consolidation_ownership(
    request: Request, operation: ConsolidationOwnershipOperation[T]
) -> T:
    """Execute one ownership operation inside the authenticated hierarchy boundary."""

    factory = get_postgres_consolidation_ownership_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="consolidation_ownership_backend_not_configured",
            message="Server consolidation-ownership backend is not configured.",
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
                PostgresConsolidationOwnershipRepository(connection, scope.tenant_id),
                scope.tenant_id,
            )
    except APIError:
        raise
    except PostgresConsolidationOwnershipError as exc:
        raise APIError(
            status_code=503,
            code="consolidation_ownership_unavailable",
            message="PostgreSQL consolidation ownership is temporarily unavailable.",
        ) from exc
    except PlatformError as exc:
        message = str(exc)
        lowered = message.casefold()
        if "not found" in lowered or "no effective" in lowered:
            raise APIError(status_code=404, code="consolidation_ownership_not_found", message=message) from exc
        if any(token in lowered for token in ("conflict", "overlap", "immutable", "more than one")):
            raise APIError(status_code=409, code="consolidation_ownership_conflict", message=message) from exc
        raise APIError(status_code=400, code="consolidation_ownership_request_invalid", message=message) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="consolidation_ownership_unavailable",
            message="PostgreSQL consolidation ownership is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="consolidation_ownership_unavailable",
            message="PostgreSQL consolidation ownership is temporarily unavailable.",
        ) from exc


__all__ = [
    "execute_postgres_consolidation_ownership",
    "get_postgres_consolidation_ownership_factory",
    "server_consolidation_ownership_enabled",
]
