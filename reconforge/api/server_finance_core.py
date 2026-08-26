"""Request-scoped PostgreSQL Finance Core operations for the server API profile.

The Finance Core adapter is deliberately separate from the legacy PostgreSQL
ledger boundary.  It carries the authenticated workspace hierarchy into the
tenant-bound repository so charts, dimensions, journals, and lifecycle
entries cannot silently fall back to local SQLite or lose workspace scope.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_identity import RequestExecutionScope, request_execution_scope
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresTenantBoundary,
    PostgresUnavailableError,
)
from reconforge.infrastructure.postgres_finance_core import (
    PostgresFinanceCoreError,
    PostgresFinanceCoreRepository,
)
from reconforge.platform.common import PlatformError
from reconforge.platform.inventory_values import code

T = TypeVar("T")
FinanceCoreOperation = Callable[[PostgresFinanceCoreRepository], T]


@dataclass(frozen=True)
class FinanceCoreExecutionScope:
    """Authenticated hierarchy plus canonical business codes for one request."""

    request: RequestExecutionScope
    organization_code: str = ""
    entity_code: str = ""

    @property
    def tenant_id(self) -> str:
        return self.request.tenant_id

    @property
    def workspace_id(self) -> str:
        return self.request.workspace_id

    @property
    def organization_id(self) -> str | None:
        return self.request.organization_id

    @property
    def legal_entity_id(self) -> str | None:
        return self.request.legal_entity_id


FinanceCoreScopedOperation = Callable[[PostgresFinanceCoreRepository, FinanceCoreExecutionScope], T]


def get_postgres_finance_core_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the configured PostgreSQL Finance Core factory, if enabled."""

    value = getattr(request.app.state, "postgres_finance_core_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_finance_core_enabled(request: Request) -> bool:
    """Return whether the tenant/workspace PostgreSQL Finance Core boundary is enabled."""

    return get_postgres_finance_core_factory(request) is not None


def _row_value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, Mapping) else row[index]


def _scope_codes(
    connection: Any,
    scope: RequestExecutionScope,
    *,
    organization_code: str = "",
    entity_code: str = "",
) -> tuple[str, str]:
    """Resolve hierarchy codes from authenticated IDs and reject spoofed payloads."""

    bound_organization = organization_code
    bound_entity = entity_code
    if scope.organization_id is not None:
        organization = connection.execute(
            "SELECT id,organization_code FROM reconforge.organizations WHERE tenant_id=%s AND id=%s",
            (scope.tenant_id, scope.organization_id),
        ).fetchone()
        if organization is None:
            raise PlatformError("Authorized Finance Core organization was not found.")
        expected_code = str(_row_value(organization, "organization_code", 1))
        linked = connection.execute(
            """SELECT 1 FROM reconforge.master_data_workspace_organizations
               WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s""",
            (scope.tenant_id, scope.workspace_id, scope.organization_id),
        ).fetchone()
        if linked is None:
            raise PlatformError("Authorized Finance Core organization is not linked to the workspace.")
        if organization_code and code(organization_code, "Organization code") != expected_code:
            raise APIError(
                status_code=403,
                code="organization_scope_denied",
                message="Organization scope is not authorized.",
            )
        bound_organization = expected_code
    if scope.legal_entity_id is not None:
        entity = connection.execute(
            """SELECT id,entity_code FROM reconforge.legal_entities
               WHERE tenant_id=%s AND organization_id=%s AND id=%s""",
            (scope.tenant_id, scope.organization_id, scope.legal_entity_id),
        ).fetchone()
        if entity is None:
            raise PlatformError("Authorized Finance Core legal entity was not found.")
        expected_code = str(_row_value(entity, "entity_code", 1))
        if entity_code and code(entity_code, "Entity code") != expected_code:
            raise APIError(
                status_code=403,
                code="entity_scope_denied",
                message="Legal-entity scope is not authorized.",
            )
        bound_entity = expected_code
    return bound_organization, bound_entity


def execute_postgres_finance_core_scoped(
    request: Request,
    operation: FinanceCoreScopedOperation[T],
    *,
    organization_code: str = "",
    entity_code: str = "",
) -> T:
    """Execute Finance Core with canonical authenticated hierarchy codes."""

    factory = get_postgres_finance_core_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="finance_core_backend_not_configured",
            message="Server Finance Core backend is not configured.",
        )
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            bound_organization, bound_entity = _scope_codes(
                connection,
                scope,
                organization_code=organization_code,
                entity_code=entity_code,
            )
            bound_scope = FinanceCoreExecutionScope(scope, bound_organization, bound_entity)
            return operation(PostgresFinanceCoreRepository(connection, scope.tenant_id), bound_scope)
    except APIError:
        raise
    except PlatformError as exc:
        raise APIError(status_code=400, code="finance_core_request_invalid", message=str(exc)) from exc
    except PostgresFinanceCoreError as exc:
        raise APIError(status_code=400, code="finance_core_request_invalid", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="finance_core_unavailable",
            message="Server Finance Core is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="finance_core_unavailable",
            message="Server Finance Core is temporarily unavailable.",
        ) from exc


def execute_postgres_finance_core(request: Request, operation: FinanceCoreOperation[T]) -> T:
    """Execute one Finance Core operation in the caller's scoped transaction."""

    factory = get_postgres_finance_core_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="finance_core_backend_not_configured",
            message="Server Finance Core backend is not configured.",
        )
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            return operation(PostgresFinanceCoreRepository(connection, scope.tenant_id))
    except APIError:
        raise
    except PlatformError as exc:
        raise APIError(status_code=400, code="finance_core_request_invalid", message=str(exc)) from exc
    except PostgresFinanceCoreError as exc:
        raise APIError(status_code=400, code="finance_core_request_invalid", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="finance_core_unavailable",
            message="Server Finance Core is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        # Driver, schema, and network details must never leak through the API.
        raise APIError(
            status_code=503,
            code="finance_core_unavailable",
            message="Server Finance Core is temporarily unavailable.",
        ) from exc
