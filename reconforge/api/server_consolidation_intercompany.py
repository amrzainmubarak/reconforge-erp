"""Request-scoped PostgreSQL execution for intercompany elimination evidence."""

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
from reconforge.infrastructure.postgres_intercompany_elimination import (
    PostgresIntercompanyEliminationError,
    PostgresIntercompanyEliminationRepository,
)
from reconforge.platform.common import PlatformError

T = TypeVar("T")
IntercompanyOperation = Callable[[PostgresIntercompanyEliminationRepository, str], T]


def get_postgres_consolidation_intercompany_factory(request: Request) -> PostgresConnectionFactory | None:
    value = getattr(request.app.state, "postgres_consolidation_intercompany_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_consolidation_intercompany_enabled(request: Request) -> bool:
    return get_postgres_consolidation_intercompany_factory(request) is not None


def execute_postgres_consolidation_intercompany(request: Request, operation: IntercompanyOperation[T]) -> T:
    factory = get_postgres_consolidation_intercompany_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="consolidation_intercompany_unavailable",
            message="PostgreSQL intercompany elimination persistence is not configured.",
        )
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            return operation(PostgresIntercompanyEliminationRepository(connection, scope.tenant_id), scope.tenant_id)
    except APIError:
        raise
    except PostgresIntercompanyEliminationError as exc:
        message = str(exc)
        lowered = message.casefold()
        if "not found" in lowered:
            raise APIError(status_code=404, code="consolidation_intercompany_not_found", message=message) from exc
        if any(token in lowered for token in ("conflict", "immutable", "cannot be deleted")):
            raise APIError(status_code=409, code="consolidation_intercompany_conflict", message=message) from exc
        if "invalid" in lowered or "verification" in lowered:
            raise APIError(status_code=400, code="consolidation_intercompany_request_invalid", message=message) from exc
        raise APIError(
            status_code=503,
            code="consolidation_intercompany_unavailable",
            message="PostgreSQL intercompany elimination persistence is temporarily unavailable.",
        ) from exc
    except PlatformError as exc:
        raise APIError(
            status_code=400,
            code="consolidation_intercompany_request_invalid",
            message=str(exc),
        ) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="consolidation_intercompany_unavailable",
            message="PostgreSQL intercompany elimination persistence is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="consolidation_intercompany_unavailable",
            message="PostgreSQL intercompany elimination persistence is temporarily unavailable.",
        ) from exc


__all__ = [
    "execute_postgres_consolidation_intercompany",
    "get_postgres_consolidation_intercompany_factory",
    "server_consolidation_intercompany_enabled",
]
