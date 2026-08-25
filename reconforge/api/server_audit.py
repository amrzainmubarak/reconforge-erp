"""Request-scoped PostgreSQL audit-administration operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_identity import get_postgres_identity_factory, request_tenant_id
from reconforge.application.audit_browsing import AuditBrowsingError
from reconforge.audit import AuditLedgerError
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresTenantBoundary,
    PostgresUnavailableError,
)
from reconforge.infrastructure.postgres_audit_browsing import PostgresAuditBrowsingRepository
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository

T = TypeVar("T")
AuditOperation = Callable[[PostgresAuditBrowsingRepository, str], T]
PolicyAuditOperation = Callable[[PostgresAuditEventRepository, str], T]


def server_audit_administration_enabled(request: Request) -> bool:
    """Return whether the PostgreSQL audit-administration boundary is available."""

    return get_postgres_identity_factory(request) is not None


def execute_postgres_audit_administration(request: Request, operation: AuditOperation[T]) -> T:
    """Execute tenant-scoped audit browsing without requiring a business scope."""

    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="audit_administration_unavailable",
            message="Audit administration requires the PostgreSQL server profile.",
        )
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresAuditBrowsingRepository(connection, tenant_id), tenant_id)
    except APIError:
        raise
    except AuditBrowsingError as exc:
        raise APIError(status_code=409, code="audit_administration_conflict", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="audit_administration_unavailable",
            message="Audit administration is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="audit_administration_unavailable",
            message="Audit administration is temporarily unavailable.",
        ) from exc


def execute_postgres_policy_audit(request: Request, operation: PolicyAuditOperation[T]) -> T:
    """Append one tenant-scoped policy decision to the domain audit chain.

    Authorization dependencies run before most route handlers and do not own a
    business transaction. This boundary therefore opens a short independent
    PostgreSQL transaction, applies the request tenant scope, and persists only
    the closed redacted evidence supplied by the policy sink.
    """

    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(
            status_code=503,
            code="authorization_audit_unavailable",
            message="Server authorization audit requires the PostgreSQL server profile.",
        )
    tenant_id = request_tenant_id(request)
    try:
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            return operation(PostgresAuditEventRepository(connection, tenant_id), tenant_id)
    except APIError:
        raise
    except AuditLedgerError as exc:
        raise APIError(
            status_code=503,
            code="authorization_audit_unavailable",
            message="Server authorization audit is temporarily unavailable.",
        ) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="authorization_audit_unavailable",
            message="Server authorization audit is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="authorization_audit_unavailable",
            message="Server authorization audit is temporarily unavailable.",
        ) from exc
