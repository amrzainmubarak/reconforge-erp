"""Request-scoped PostgreSQL control-plane export operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_identity import request_execution_scope
from reconforge.application.scoped_exports import ScopedExportError, ScopedExportScope
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresUnavailableError,
)
from reconforge.infrastructure.postgres_scoped_exports import PostgresScopedExportRepository

T = TypeVar("T")
ScopedExportOperation = Callable[[PostgresScopedExportRepository, ScopedExportScope], T]


def get_postgres_scoped_exports_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the explicitly configured server export connection factory."""

    value = getattr(request.app.state, "postgres_scoped_exports_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_scoped_exports_enabled(request: Request) -> bool:
    """Return whether the PostgreSQL scoped-export profile is available."""

    return get_postgres_scoped_exports_factory(request) is not None


def execute_postgres_scoped_export(request: Request, operation: ScopedExportOperation[T]) -> T:
    """Execute one hierarchy-bound export operation with safe API errors."""

    factory = get_postgres_scoped_exports_factory(request)
    if factory is None:
        raise APIError(
            status_code=501,
            code="scoped_export_server_only",
            message="Scoped control-plane exports require the explicit PostgreSQL server profile.",
        )
    scope = request_execution_scope(request)
    export_scope = ScopedExportScope(
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        organization_id=scope.organization_id or "",
        entity_id=scope.legal_entity_id or "",
    )
    try:
        repository = PostgresScopedExportRepository(factory)
        return operation(repository, export_scope)
    except APIError:
        raise
    except ScopedExportError as exc:
        raise APIError(
            status_code=400,
            code="scoped_export_invalid",
            message="The scoped export request or result is invalid.",
        ) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="scoped_export_unavailable",
            message="The scoped export backend is temporarily unavailable.",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - no database/provider details cross the API boundary.
        raise APIError(
            status_code=503,
            code="scoped_export_unavailable",
            message="The scoped export backend is temporarily unavailable.",
        ) from exc


__all__ = [
    "execute_postgres_scoped_export",
    "get_postgres_scoped_exports_factory",
    "server_scoped_exports_enabled",
]
