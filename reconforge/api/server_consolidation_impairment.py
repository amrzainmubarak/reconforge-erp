"""Request-scoped PostgreSQL execution for non-posting impairment evidence."""

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
from reconforge.infrastructure.postgres_consolidation_impairment import (
    PostgresConsolidationImpairmentError,
    PostgresConsolidationImpairmentRepository,
)
from reconforge.platform.common import PlatformError

T = TypeVar("T")
ImpairmentOperation = Callable[[PostgresConsolidationImpairmentRepository, str], T]


def get_postgres_impairment_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the explicit server-profile impairment factory, if configured."""

    value = getattr(request.app.state, "postgres_consolidation_impairment_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_impairment_enabled(request: Request) -> bool:
    """Return whether impairment persistence uses the PostgreSQL server boundary."""

    return get_postgres_impairment_factory(request) is not None


def execute_postgres_impairment(request: Request, operation: ImpairmentOperation[T]) -> T:
    """Execute one impairment operation inside a tenant-local RLS transaction."""

    factory = get_postgres_impairment_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="consolidation_impairment_unavailable",
            message="PostgreSQL consolidation impairment persistence is not configured.",
        )
    tenant_id = request_tenant_id(request)
    organization_id, legal_entity_id = request_optional_hierarchy(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            tenant_id,
            organization_id=organization_id,
            legal_entity_id=legal_entity_id,
        ) as connection:
            return operation(
                PostgresConsolidationImpairmentRepository(connection, tenant_id, organization_id, legal_entity_id),
                tenant_id,
            )
    except APIError:
        raise
    except PlatformError as exc:
        raise APIError(
            status_code=400,
            code="consolidation_impairment_request_invalid",
            message=str(exc),
        ) from exc
    except PostgresConsolidationImpairmentError as exc:
        message = str(exc)
        if "not found" in message.casefold():
            raise APIError(status_code=404, code="consolidation_impairment_not_found", message=message) from exc
        if any(token in message.casefold() for token in ("conflict", "immutable", "cannot be deleted")):
            raise APIError(status_code=409, code="consolidation_impairment_conflict", message=message) from exc
        if "verification" in message.casefold() or "invalid" in message.casefold():
            raise APIError(
                status_code=400,
                code="consolidation_impairment_request_invalid",
                message=message,
            ) from exc
        raise APIError(
            status_code=503,
            code="consolidation_impairment_unavailable",
            message="PostgreSQL consolidation impairment persistence is temporarily unavailable.",
        ) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="consolidation_impairment_unavailable",
            message="PostgreSQL consolidation impairment persistence is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="consolidation_impairment_unavailable",
            message="PostgreSQL consolidation impairment persistence is temporarily unavailable.",
        ) from exc


__all__ = [
    "execute_postgres_impairment",
    "get_postgres_impairment_factory",
    "server_impairment_enabled",
]
