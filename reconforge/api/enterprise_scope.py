"""One authenticated PostgreSQL scope for the enterprise application routes.

Selecting a PostgreSQL backend is explicit. Connection or authorization failure
never changes that selection to a local SQLite database.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal, cast

from fastapi import Request

from reconforge.api.dependencies import enforce_server_scoped_permissions
from reconforge.api.errors import APIError
from reconforge.api.server_identity import (
    RequestExecutionScope,
    request_execution_scope,
    server_identity_enabled,
)
from reconforge.infrastructure.postgres import (
    ConnectionFactory,
    PostgresConfigurationError,
    PostgresTenantBoundary,
    PostgresUnavailableError,
)


@dataclass(frozen=True)
class EnterpriseExecutionScope:
    hierarchy: RequestExecutionScope
    connection_factory: ConnectionFactory

    @property
    def tenant_id(self) -> str:
        return self.hierarchy.tenant_id

    @property
    def workspace_id(self) -> str:
        return self.hierarchy.workspace_id


@dataclass(frozen=True)
class EnterpriseTransaction:
    connection: Any
    scope: EnterpriseExecutionScope


def enterprise_scope(
    request: Request,
    *,
    permissions: frozenset[str],
    permission_mode: Literal["all", "any"] = "all",
    require_hierarchy: bool = False,
) -> EnterpriseExecutionScope | None:
    """Bind real header hierarchy and current human/service authority before I/O."""
    if not permissions or permission_mode not in {"all", "any"}:
        raise ValueError("An explicit nonempty enterprise permission contract is required.")
    factories = (
        getattr(request.app.state, "postgres_finance_core_factory", None),
        getattr(request.app.state, "postgres_identity_factory", None),
        getattr(request.app.state, "postgres_connection_factory", None),
    )
    selected = next((candidate for candidate in factories if candidate is not None), None)
    if selected is None:
        if bool(getattr(request.app.state, "server_mode", False)):
            raise APIError(status_code=503, code="server_postgres_unavailable", message="Enterprise mode requires PostgreSQL.")
        return None
    if not callable(getattr(selected, "connect", None)) or not server_identity_enabled(request):
        raise APIError(
            status_code=503,
            code="server_identity_unavailable",
            message="The selected PostgreSQL backend requires server authentication.",
        )
    if permission_mode == "all":
        # Each capability must independently pass current scoped policy. A set
        # passed to the existing plural helper intentionally has ANY semantics.
        scope = None
        for permission in sorted(permissions):
            scope = request_execution_scope(request, permission=permission)
        if scope is None:
            raise APIError(status_code=403, code="permission_denied", message="Permission denied.")
    else:
        scope = request_execution_scope(request)
        enforce_server_scoped_permissions(
            request,
            permissions=permissions,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            organization_id=scope.organization_id,
            entity_id=scope.legal_entity_id,
        )
    if require_hierarchy and (scope.organization_id is None or scope.legal_entity_id is None):
        raise APIError(status_code=400, code="entity_scope_required", message="An explicit organization and legal entity are required.")
    # These are compatibility aliases only after the current header/principal
    # boundary has admitted the scope. They are never an input to authorization.
    request.state.tenant_id = scope.tenant_id
    request.state.workspace_id = scope.workspace_id
    request.state.organization_id = scope.organization_id
    request.state.legal_entity_id = scope.legal_entity_id
    return EnterpriseExecutionScope(scope, cast(ConnectionFactory, selected))


@dataclass(frozen=True)
class _AvailableFactory:
    delegate: ConnectionFactory

    def connect(self) -> Any:
        try:
            return self.delegate.connect()
        except Exception as exc:
            raise APIError(
                status_code=503,
                code="server_postgres_unavailable",
                message="The selected PostgreSQL backend is temporarily unavailable.",
            ) from exc


@contextmanager
def enterprise_transaction(
    request: Request,
    *,
    permissions: frozenset[str],
    permission_mode: Literal["all", "any"] = "all",
    require_hierarchy: bool = False,
) -> Iterator[EnterpriseTransaction | None]:
    """Own commit/rollback/close and GUC hierarchy for an admitted request."""
    scope = enterprise_scope(request, permissions=permissions, permission_mode=permission_mode, require_hierarchy=require_hierarchy)
    if scope is None:
        yield None
        return
    try:
        with PostgresTenantBoundary(_AvailableFactory(scope.connection_factory)).transaction(
            scope.tenant_id,
            organization_id=scope.hierarchy.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.hierarchy.legal_entity_id,
        ) as connection:
            yield EnterpriseTransaction(connection, scope)
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="server_postgres_unavailable",
            message="The selected PostgreSQL backend is temporarily unavailable.",
        ) from exc
