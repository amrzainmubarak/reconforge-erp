"""Request-scoped PostgreSQL account-reconciliation operations."""

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
from reconforge.infrastructure.postgres_accounts import PostgresAccountReconciliationRepository
from reconforge.platform.common import PlatformError

T = TypeVar("T")
AccountOperation = Callable[[PostgresAccountReconciliationRepository, str], T]


def get_postgres_accounts_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured PostgreSQL account-reconciliation factory."""

    value = getattr(request.app.state, "postgres_accounts_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_accounts_enabled(request: Request) -> bool:
    """Return whether account-reconciliation routes must use PostgreSQL."""

    return get_postgres_accounts_factory(request) is not None


def execute_postgres_accounts(request: Request, operation: AccountOperation[T]) -> T:
    """Execute one account-reconciliation operation in the request scope."""

    factory = get_postgres_accounts_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="accounts_backend_not_configured",
            message="Server account-reconciliation backend is not configured.",
        )
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            return operation(PostgresAccountReconciliationRepository(connection, scope.tenant_id), scope.tenant_id)
    except APIError:
        raise
    except PlatformError as exc:
        raise APIError(status_code=400, code="accounts_request_invalid", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="accounts_unavailable",
            message="Server account reconciliation is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="accounts_unavailable",
            message="Server account reconciliation is temporarily unavailable.",
        ) from exc
