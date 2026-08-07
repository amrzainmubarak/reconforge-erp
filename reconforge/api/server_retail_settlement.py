"""Request-scoped PostgreSQL retail settlement evidence operations."""

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
from reconforge.infrastructure.postgres_retail_settlement import (
    PostgresRetailSettlementPersistenceError,
    PostgresRetailSettlementRepository,
)

T = TypeVar("T")
RetailSettlementOperation = Callable[[PostgresRetailSettlementRepository, str, str], T]


def get_postgres_retail_settlement_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the explicitly configured PostgreSQL retail factory."""

    value = getattr(request.app.state, "postgres_retail_settlement_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_retail_settlement_enabled(request: Request) -> bool:
    """Return whether retail persistence must use PostgreSQL server mode."""

    return get_postgres_retail_settlement_factory(request) is not None


def execute_postgres_retail_settlement(
    request: Request,
    operation: RetailSettlementOperation[T],
) -> T:
    """Execute one tenant/workspace-scoped retail operation."""

    factory = get_postgres_retail_settlement_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="retail_settlement_backend_not_configured",
            message="Server retail settlement persistence is not configured.",
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
                PostgresRetailSettlementRepository(connection),
                scope.tenant_id,
                scope.workspace_id,
            )
    except APIError:
        raise
    except PostgresRetailSettlementPersistenceError as exc:
        status = 409 if "conflicts" in str(exc) else 400
        raise APIError(status_code=status, code="retail_settlement_persistence_failed", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="retail_settlement_unavailable",
            message="Server retail settlement persistence is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="retail_settlement_unavailable",
            message="Server retail settlement persistence is temporarily unavailable.",
        ) from exc


__all__ = [
    "execute_postgres_retail_settlement",
    "get_postgres_retail_settlement_factory",
    "server_retail_settlement_enabled",
]
