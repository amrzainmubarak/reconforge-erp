"""Request-scoped PostgreSQL Finance Core operations for the server API profile.

The Finance Core adapter is deliberately separate from the legacy PostgreSQL
ledger boundary.  It carries the authenticated workspace hierarchy into the
tenant-bound repository so charts, dimensions, journals, and lifecycle
entries cannot silently fall back to local SQLite or lose workspace scope.
"""

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
from reconforge.infrastructure.postgres_finance_core import (
    PostgresFinanceCoreError,
    PostgresFinanceCoreRepository,
)
from reconforge.platform.common import PlatformError

T = TypeVar("T")
FinanceCoreOperation = Callable[[PostgresFinanceCoreRepository], T]


def get_postgres_finance_core_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured PostgreSQL Finance Core factory, if enabled."""

    value = getattr(request.app.state, "postgres_finance_core_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_finance_core_enabled(request: Request) -> bool:
    """Return whether the tenant/workspace PostgreSQL Finance Core boundary is enabled."""

    return get_postgres_finance_core_factory(request) is not None


def execute_postgres_finance_core(request: Request, operation: FinanceCoreOperation[T]) -> T:
    """Execute one Finance Core operation in the caller's scoped transaction."""

    factory = get_postgres_finance_core_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="finance_core_backend_not_configured",
            message="Server Finance Core backend is not configured.",
        )
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            return operation(PostgresFinanceCoreRepository(connection, scope.tenant_id))
    except APIError:
        raise
    except PlatformError as exc:
        raise APIError(status_code=400, code="finance_core_request_invalid", message=str(exc)) from exc
    except PostgresFinanceCoreError as exc:
        raise APIError(status_code=400, code="finance_core_request_invalid", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="finance_core_unavailable",
            message="Server Finance Core is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        # Driver, schema, and network details must never leak through the API.
        raise APIError(
            status_code=503,
            code="finance_core_unavailable",
            message="Server Finance Core is temporarily unavailable.",
        ) from exc
