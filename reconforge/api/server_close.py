"""Request-scoped PostgreSQL close-control operations for server mode."""

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
from reconforge.infrastructure.postgres_close import (
    PostgresCloseIntegrityError,
    PostgresCloseNotFoundError,
    PostgresCloseRepository,
    PostgresCloseValidationError,
)

T = TypeVar("T")
CloseOperation = Callable[[PostgresCloseRepository, str], T]


def get_postgres_close_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured PostgreSQL close-control factory, if enabled."""

    value = getattr(request.app.state, "postgres_close_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_close_enabled(request: Request) -> bool:
    """Return whether close routes must use PostgreSQL."""

    return get_postgres_close_factory(request) is not None


def execute_postgres_close(request: Request, operation: CloseOperation[T]) -> T:
    """Execute one close-control operation in a tenant-scoped transaction."""

    factory = get_postgres_close_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="close_backend_not_configured",
            message="Server close backend is not configured.",
        )
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            return operation(PostgresCloseRepository(connection), scope.tenant_id)
    except APIError:
        raise
    except PostgresCloseValidationError as exc:
        raise APIError(status_code=400, code="close_request_invalid", message=str(exc)) from exc
    except PostgresCloseNotFoundError as exc:
        raise APIError(status_code=404, code="close_record_not_found", message=str(exc)) from exc
    except PostgresCloseIntegrityError as exc:
        raise APIError(status_code=409, code="close_conflict", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="close_unavailable",
            message="Server close control is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="close_unavailable",
            message="Server close control is temporarily unavailable.",
        ) from exc
