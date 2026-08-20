"""Request-scoped PostgreSQL execution for ownership-change evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_identity import request_optional_hierarchy, request_tenant_id
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresTenantBoundary,
    PostgresUnavailableError,
)
from reconforge.infrastructure.postgres_consolidation_ownership_change import (
    PostgresConsolidationOwnershipChangeError,
    PostgresConsolidationOwnershipChangeRepository,
)
from reconforge.platform.common import PlatformError

T = TypeVar("T")
OwnershipChangeOperation = Callable[[PostgresConsolidationOwnershipChangeRepository, str], T]


def get_postgres_ownership_change_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the explicit server-profile ownership-change factory, if configured."""

    value = getattr(request.app.state, "postgres_consolidation_ownership_change_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_ownership_change_enabled(request: Request) -> bool:
    """Return whether ownership-change persistence uses the PostgreSQL server boundary."""

    return get_postgres_ownership_change_factory(request) is not None


def execute_postgres_ownership_change(request: Request, operation: OwnershipChangeOperation[T]) -> T:
    """Execute one ownership-change operation inside a tenant-local RLS transaction."""

    factory = get_postgres_ownership_change_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="consolidation_ownership_change_unavailable",
            message="PostgreSQL consolidation ownership-change persistence is not configured.",
        )
    tenant_id = request_tenant_id(request)
    organization_id, legal_entity_id = request_optional_hierarchy(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            tenant_id,
            organization_id=organization_id,
            legal_entity_id=legal_entity_id,
        ) as connection:
            return operation(PostgresConsolidationOwnershipChangeRepository(connection, tenant_id), tenant_id)
    except APIError:
        raise
    except PlatformError as exc:
        raise APIError(
            status_code=400,
            code="consolidation_ownership_change_request_invalid",
            message=str(exc),
        ) from exc
    except PostgresConsolidationOwnershipChangeError as exc:
        message = str(exc)
        folded = message.casefold()
        if "not found" in folded:
            raise APIError(status_code=404, code="consolidation_ownership_change_not_found", message=message) from exc
        if any(token in folded for token in ("conflict", "immutable", "cannot be deleted")):
            raise APIError(status_code=409, code="consolidation_ownership_change_conflict", message=message) from exc
        if "verification" in folded or "invalid" in folded:
            raise APIError(
                status_code=400,
                code="consolidation_ownership_change_request_invalid",
                message=message,
            ) from exc
        raise APIError(
            status_code=503,
            code="consolidation_ownership_change_unavailable",
            message="PostgreSQL consolidation ownership-change persistence is temporarily unavailable.",
        ) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="consolidation_ownership_change_unavailable",
            message="PostgreSQL consolidation ownership-change persistence is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="consolidation_ownership_change_unavailable",
            message="PostgreSQL consolidation ownership-change persistence is temporarily unavailable.",
        ) from exc


__all__ = [
    "execute_postgres_ownership_change",
    "get_postgres_ownership_change_factory",
    "server_ownership_change_enabled",
]
