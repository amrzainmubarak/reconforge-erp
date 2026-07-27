"""Request-scoped PostgreSQL identity operations for the server API profile.

The current server profile keeps legacy domain routes on the existing
database-per-tenant SQLite router while identity and session authority live in
PostgreSQL. This module deliberately opens one short tenant-scoped transaction
per identity operation; it never falls back to a shared SQLite identity store
when the server profile is enabled.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresTenantBoundary,
    PostgresUnavailableError,
    validate_tenant_id,
)
from reconforge.infrastructure.postgres_identity import (
    PostgresIdentityError,
    PostgresIdentityRepository,
    PostgresIdentityValidationError,
)

T = TypeVar("T")
IdentityOperation = Callable[[PostgresIdentityRepository, str], T]


def get_postgres_identity_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured server identity factory, if server mode is enabled."""

    value = getattr(request.app.state, "postgres_identity_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_identity_enabled(request: Request) -> bool:
    """Return whether this request is served by the PostgreSQL identity profile."""

    return get_postgres_identity_factory(request) is not None


def request_tenant_id(request: Request) -> str:
    """Validate and return the required tenant header for server identity."""

    raw_tenant = request.headers.get("x-reconforge-tenant", "")
    if not raw_tenant:
        raise APIError(
            status_code=400,
            code="tenant_required",
            message="X-ReconForge-Tenant is required for server authentication.",
        )
    try:
        return validate_tenant_id(raw_tenant)
    except PostgresConfigurationError as exc:
        raise APIError(status_code=400, code="invalid_tenant", message=str(exc)) from exc


def execute_postgres_identity(request: Request, operation: IdentityOperation[T]) -> T:
    """Execute one identity operation inside a transaction-local RLS scope."""

    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="identity_backend_not_configured",
            message="Server identity backend is not configured.",
        )
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresIdentityRepository(connection), tenant_id)
    except APIError:
        raise
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="identity_unavailable",
            message="Server identity is temporarily unavailable.",
        ) from exc
    except PostgresIdentityValidationError as exc:
        raise APIError(status_code=400, code="identity_request_invalid", message=str(exc)) from exc
    except PostgresIdentityError as exc:
        raise APIError(
            status_code=503,
            code="identity_unavailable",
            message="Server identity is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        # psycopg is optional and intentionally not imported here. Any driver
        # or network failure is sanitized into the same fail-closed response.
        raise APIError(
            status_code=503,
            code="identity_unavailable",
            message="Server identity is temporarily unavailable.",
        ) from exc


def authenticate_server_request(
    request: Request,
    token: str,
) -> tuple[LocalUser, frozenset[str]] | None:
    """Authenticate one bearer token and snapshot permissions for middleware."""

    return execute_postgres_identity(request, _authenticate_and_snapshot(token))


def _authenticate_and_snapshot(token: str) -> IdentityOperation[tuple[LocalUser, frozenset[str]] | None]:
    def operation(repository: PostgresIdentityRepository, tenant_id: str) -> tuple[LocalUser, frozenset[str]] | None:
        user = repository.authenticate_token(tenant_id=tenant_id, token=token)
        if user is None:
            return None
        return user, repository.user_permissions(tenant_id=tenant_id, user_id=user.id)

    return operation


def server_identity_state(request: Request) -> dict[str, Any]:
    """Return non-secret diagnostics for the configured identity profile."""

    return {
        "backend": "postgresql" if server_identity_enabled(request) else "sqlite",
        "tenant_header_required": server_identity_enabled(request),
    }
