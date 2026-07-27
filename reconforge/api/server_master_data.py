"""Request-scoped PostgreSQL master-data operations for server mode."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_identity import request_tenant_id
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresTenantBoundary,
    PostgresUnavailableError,
)
from reconforge.infrastructure.postgres_master_data import (
    PostgresMasterDataError,
    PostgresMasterDataRepository,
    PostgresMasterDataValidationError,
)

T = TypeVar("T")
MasterDataOperation = Callable[[PostgresMasterDataRepository, str], T]


def get_postgres_master_data_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured PostgreSQL master-data factory."""

    value = getattr(request.app.state, "postgres_master_data_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_master_data_enabled(request: Request) -> bool:
    """Return whether master-data routes must use PostgreSQL."""

    return get_postgres_master_data_factory(request) is not None


def execute_postgres_master_data(request: Request, operation: MasterDataOperation[T]) -> T:
    """Execute a master-data operation inside one tenant-scoped transaction."""

    factory = get_postgres_master_data_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="master_data_backend_not_configured",
            message="Server master-data backend is not configured.",
        )
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresMasterDataRepository(connection), tenant_id)
    except APIError:
        raise
    except PostgresMasterDataValidationError as exc:
        raise APIError(status_code=400, code="master_data_request_invalid", message=str(exc)) from exc
    except PostgresMasterDataError as exc:
        raise APIError(status_code=404, code="master_data_record_not_found", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="master_data_unavailable",
            message="Server master data is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="master_data_unavailable",
            message="Server master data is temporarily unavailable.",
        ) from exc
