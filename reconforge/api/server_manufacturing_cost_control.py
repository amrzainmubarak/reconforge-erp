"""Request-scoped PostgreSQL manufacturing evidence operations."""

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
from reconforge.infrastructure.postgres_manufacturing_cost_control import (
    PostgresManufacturingCostControlPersistenceError,
    PostgresManufacturingCostControlRepository,
)

T = TypeVar("T")
ManufacturingCostControlOperation = Callable[[PostgresManufacturingCostControlRepository, str, str], T]


def get_postgres_manufacturing_cost_control_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the explicitly configured PostgreSQL manufacturing factory."""

    value = getattr(request.app.state, "postgres_manufacturing_cost_control_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_manufacturing_cost_control_enabled(request: Request) -> bool:
    """Return whether manufacturing persistence is configured for server mode."""

    return get_postgres_manufacturing_cost_control_factory(request) is not None


def execute_postgres_manufacturing_cost_control(
    request: Request,
    operation: ManufacturingCostControlOperation[T],
) -> T:
    """Execute one tenant/workspace-scoped manufacturing operation."""

    factory = get_postgres_manufacturing_cost_control_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="manufacturing_cost_control_backend_not_configured",
            message="Server manufacturing cost-control persistence is not configured.",
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
                PostgresManufacturingCostControlRepository(connection),
                scope.tenant_id,
                scope.workspace_id,
            )
    except APIError:
        raise
    except PostgresManufacturingCostControlPersistenceError as exc:
        status = 409 if "conflicts" in str(exc) else 400
        raise APIError(
            status_code=status,
            code="manufacturing_cost_control_persistence_failed",
            message=str(exc),
        ) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="manufacturing_cost_control_unavailable",
            message="Server manufacturing cost-control persistence is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="manufacturing_cost_control_unavailable",
            message="Server manufacturing cost-control persistence is temporarily unavailable.",
        ) from exc


__all__ = [
    "execute_postgres_manufacturing_cost_control",
    "get_postgres_manufacturing_cost_control_factory",
    "server_manufacturing_cost_control_enabled",
]
