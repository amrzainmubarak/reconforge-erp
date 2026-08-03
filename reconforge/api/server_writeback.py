"""Request-scoped PostgreSQL write-back intent operations for server mode.

This boundary persists only the immutable, digest-bound intent lifecycle.  It
does not resolve secrets or dispatch provider network calls.
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
from reconforge.infrastructure.postgres_writeback import (
    PostgresWritebackIntentRepository,
    PostgresWritebackPersistenceError,
)

T = TypeVar("T")
WritebackOperation = Callable[[PostgresWritebackIntentRepository, str, str], T]


def get_postgres_writeback_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured PostgreSQL write-back persistence factory."""

    value = getattr(request.app.state, "postgres_writeback_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_writeback_enabled(request: Request) -> bool:
    """Return whether write-back intent routes must use PostgreSQL."""

    return get_postgres_writeback_factory(request) is not None


def execute_postgres_writeback(request: Request, operation: WritebackOperation[T]) -> T:
    """Execute one tenant/workspace-scoped intent operation."""

    factory = get_postgres_writeback_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="writeback_backend_not_configured",
            message="Server write-back persistence is not configured.",
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
                PostgresWritebackIntentRepository(connection),
                scope.tenant_id,
                scope.workspace_id,
            )
    except APIError:
        raise
    except PostgresWritebackPersistenceError as exc:
        raise APIError(status_code=409, code="writeback_intent_conflict", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="writeback_unavailable",
            message="Server write-back persistence is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="writeback_unavailable",
            message="Server write-back persistence is temporarily unavailable.",
        ) from exc


__all__ = [
    "execute_postgres_writeback",
    "get_postgres_writeback_factory",
    "server_writeback_enabled",
]
