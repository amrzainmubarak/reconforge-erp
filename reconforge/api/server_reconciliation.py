"""Request-scoped PostgreSQL reconciliation read operations for server mode."""

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
from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationIntegrityError,
    PostgresReconciliationNotFoundError,
    PostgresReconciliationRepository,
    PostgresReconciliationValidationError,
)

T = TypeVar("T")
ReconciliationOperation = Callable[[PostgresReconciliationRepository, str], T]


def get_postgres_reconciliation_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured PostgreSQL reconciliation factory, if enabled."""

    value = getattr(request.app.state, "postgres_reconciliation_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_reconciliation_enabled(request: Request) -> bool:
    """Return whether reconciliation read routes must use PostgreSQL."""

    return get_postgres_reconciliation_factory(request) is not None


def execute_postgres_reconciliation(request: Request, operation: ReconciliationOperation[T]) -> T:
    """Execute one tenant-scoped read operation in a caller-owned transaction."""

    factory = get_postgres_reconciliation_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="reconciliation_backend_not_configured",
            message="Server reconciliation backend is not configured.",
        )
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            return operation(PostgresReconciliationRepository(connection), scope.tenant_id)
    except APIError:
        raise
    except PostgresReconciliationValidationError as exc:
        raise APIError(status_code=400, code="reconciliation_request_invalid", message=str(exc)) from exc
    except PostgresReconciliationNotFoundError as exc:
        raise APIError(status_code=404, code="reconciliation_run_not_found", message=str(exc)) from exc
    except PostgresReconciliationIntegrityError as exc:
        raise APIError(status_code=409, code="reconciliation_conflict", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="reconciliation_unavailable",
            message="Server reconciliation results are temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="reconciliation_unavailable",
            message="Server reconciliation results are temporarily unavailable.",
        ) from exc
