"""Request-scoped PostgreSQL ledger operations for the server API profile.

The server ledger profile is deliberately bounded.  It serves the real
PostgreSQL account and posted-entry repository; it never falls back to the
legacy SQLite Finance Core service when PostgreSQL server mode is enabled.
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
from reconforge.infrastructure.postgres_ledger import (
    PostgresLedgerIntegrityError,
    PostgresLedgerNotFoundError,
    PostgresLedgerRepository,
    PostgresLedgerValidationError,
)

T = TypeVar("T")
LedgerOperation = Callable[[PostgresLedgerRepository, str], T]


def get_postgres_ledger_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured server ledger factory, if server mode is enabled."""

    value = getattr(request.app.state, "postgres_ledger_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_ledger_enabled(request: Request) -> bool:
    """Return whether Finance Core must use the PostgreSQL ledger boundary."""

    return get_postgres_ledger_factory(request) is not None


def execute_postgres_ledger(request: Request, operation: LedgerOperation[T]) -> T:
    """Execute one ledger operation in a tenant-scoped caller transaction."""

    factory = get_postgres_ledger_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="ledger_backend_not_configured",
            message="Server ledger backend is not configured.",
        )
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            return operation(PostgresLedgerRepository(connection), scope.tenant_id)
    except APIError:
        raise
    except PostgresLedgerValidationError as exc:
        raise APIError(status_code=400, code="ledger_request_invalid", message=str(exc)) from exc
    except PostgresLedgerNotFoundError as exc:
        raise APIError(status_code=404, code="ledger_record_not_found", message=str(exc)) from exc
    except PostgresLedgerIntegrityError as exc:
        raise APIError(status_code=409, code="ledger_conflict", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="ledger_unavailable",
            message="Server ledger is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        # psycopg is optional and intentionally not imported here.  Driver,
        # schema, and network failures must not leak SQL or stack details.
        raise APIError(
            status_code=503,
            code="ledger_unavailable",
            message="Server ledger is temporarily unavailable.",
        ) from exc
