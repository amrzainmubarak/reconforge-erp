"""Request-scoped PostgreSQL evidence operations for server mode."""

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
from reconforge.infrastructure.postgres_evidence import (
    PostgresEvidenceIntegrityError,
    PostgresEvidenceNotFoundError,
    PostgresEvidenceRepository,
    PostgresEvidenceValidationError,
)

T = TypeVar("T")
EvidenceOperation = Callable[[PostgresEvidenceRepository, str], T]


def get_postgres_evidence_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured server evidence connection factory."""

    value = getattr(request.app.state, "postgres_evidence_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_evidence_enabled(request: Request) -> bool:
    """Return whether evidence routes must use PostgreSQL."""

    return get_postgres_evidence_factory(request) is not None


def execute_postgres_evidence(request: Request, operation: EvidenceOperation[T]) -> T:
    """Execute one evidence operation in a tenant-scoped caller transaction."""

    factory = get_postgres_evidence_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="evidence_backend_not_configured",
            message="Server evidence backend is not configured.",
        )
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresEvidenceRepository(connection), tenant_id)
    except APIError:
        raise
    except PostgresEvidenceValidationError as exc:
        raise APIError(status_code=400, code="evidence_request_invalid", message=str(exc)) from exc
    except PostgresEvidenceNotFoundError as exc:
        raise APIError(status_code=404, code="evidence_record_not_found", message=str(exc)) from exc
    except PostgresEvidenceIntegrityError as exc:
        raise APIError(status_code=409, code="evidence_conflict", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="evidence_unavailable",
            message="Server evidence registry is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="evidence_unavailable",
            message="Server evidence registry is temporarily unavailable.",
        ) from exc
