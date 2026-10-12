"""Request-scoped PostgreSQL Inventory Core operations."""

from __future__ import annotations

from collections.abc import Callable
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
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.platform.common import PlatformError
from reconforge.platform.inventory_values import code

T = TypeVar("T")


@dataclass(frozen=True)
class InventoryExecutionScope:
    """Authenticated IDs plus the canonical codes required by the adapter."""

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


InventoryOperation = Callable[[PostgresInventoryCoreRepository, InventoryExecutionScope], T]


def get_postgres_inventory_factory(request: Request) -> PostgresConnectionFactory | None:
    """Return the explicitly configured PostgreSQL Inventory Core factory."""

    value = getattr(request.app.state, "postgres_inventory_core_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_inventory_core_enabled(request: Request) -> bool:
    """Return whether Inventory Core must use the PostgreSQL server adapter."""

    return get_postgres_inventory_factory(request) is not None


def _scope_code(
    connection: Any,
    scope: RequestExecutionScope,
    *,
    organization_code: str = "",
    entity_code: str = "",
) -> tuple[str, str]:
    """Bind optional human-readable codes to the authenticated hierarchy IDs."""

    bound_organization = organization_code
    bound_entity = entity_code
    if scope.organization_id is not None:
        organization = connection.execute(
            "SELECT id,organization_code FROM reconforge.organizations WHERE tenant_id=%s AND id=%s",
            (scope.tenant_id, scope.organization_id),
        ).fetchone()
        if organization is None:
            raise PlatformError("Authorized inventory organization was not found.")
        actual_organization_id = str(organization["id"] if hasattr(organization, "keys") else organization[0])
        expected_organization = str(
            organization["organization_code"] if hasattr(organization, "keys") else organization[1]
        )
        if actual_organization_id != scope.organization_id:
            raise APIError(
                status_code=403,
                code="organization_scope_denied",
                message="Organization scope is not authorized.",
            )
        linked = connection.execute(
            "SELECT 1 FROM reconforge.master_data_workspace_organizations "
            "WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s",
            (scope.tenant_id, scope.workspace_id, scope.organization_id),
        ).fetchone()
        if linked is None:
            raise PlatformError("Authorized inventory organization is not linked to the workspace.")
        if organization_code and code(organization_code, "Organization code") != expected_organization:
            raise APIError(
                status_code=403,
                code="organization_scope_denied",
                message="Organization scope is not authorized.",
            )
        bound_organization = expected_organization
    if scope.legal_entity_id is not None:
        entity = connection.execute(
            """SELECT id,entity_code FROM reconforge.legal_entities
            WHERE tenant_id=%s AND organization_id=%s
              AND ((id=%s AND %s='') OR entity_code=%s)""",
            (scope.tenant_id, scope.organization_id, scope.legal_entity_id, entity_code, entity_code),
        ).fetchone()
        if entity is None:
            raise PlatformError("Authorized inventory legal entity was not found.")
        actual_entity_id = str(entity["id"] if hasattr(entity, "keys") else entity[0])
        expected_entity = str(entity["entity_code"] if hasattr(entity, "keys") else entity[1])
        if actual_entity_id != scope.legal_entity_id:
            raise APIError(
                status_code=403,
                code="entity_scope_denied",
                message="Legal-entity scope is not authorized.",
            )
        if entity_code and code(entity_code, "Entity code") != expected_entity:
            raise APIError(
                status_code=403,
                code="entity_scope_denied",
                message="Legal-entity scope is not authorized.",
            )
        bound_entity = expected_entity
    return bound_organization, bound_entity


def _validate_movement_scope(connection: Any, scope: RequestExecutionScope, movement_id: str) -> None:
    row = connection.execute(
        "SELECT workspace_id,organization_id,legal_entity_id FROM reconforge.inventory_movements "
        "WHERE tenant_id=%s AND id=%s",
        (scope.tenant_id, movement_id),
    ).fetchone()
    if row is None:
        return
    workspace_id = str(row["workspace_id"] if hasattr(row, "keys") else row[0])
    organization_id = str(row["organization_id"] if hasattr(row, "keys") else row[1])
    entity_id = str(row["legal_entity_id"] if hasattr(row, "keys") else row[2])
    if workspace_id != scope.workspace_id:
        raise APIError(status_code=403, code="workspace_scope_denied", message="Workspace scope is not authorized.")
    if scope.organization_id is not None and organization_id != scope.organization_id:
        raise APIError(
            status_code=403,
            code="organization_scope_denied",
            message="Organization scope is not authorized.",
        )
    if scope.legal_entity_id is not None and entity_id != scope.legal_entity_id:
        raise APIError(status_code=403, code="entity_scope_denied", message="Legal-entity scope is not authorized.")


def execute_postgres_inventory(
    request: Request,
    operation: InventoryOperation[T],
    *,
    organization_code: str = "",
    entity_code: str = "",
    movement_id: str | None = None,
) -> T:
    """Execute one Inventory Core operation with transaction-local hierarchy scope."""

    factory = get_postgres_inventory_factory(request)
    if factory is None:
        raise APIError(
            status_code=500,
            code="inventory_backend_not_configured",
            message="Server Inventory Core backend is not configured.",
        )
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            bound_organization, bound_entity = _scope_code(
                connection,
                scope,
                organization_code=organization_code,
                entity_code=entity_code,
            )
            if movement_id is not None:
                _validate_movement_scope(connection, scope, movement_id)
            bound_scope = InventoryExecutionScope(
                request=scope,
                organization_code=bound_organization,
                entity_code=bound_entity,
            )
            return operation(PostgresInventoryCoreRepository(connection, scope.tenant_id), bound_scope)
    except APIError:
        raise
    except PlatformError as exc:
        raise APIError(status_code=400, code="inventory_request_invalid", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(
            status_code=503,
            code="inventory_unavailable",
            message="Server Inventory Core is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise APIError(
            status_code=503,
            code="inventory_unavailable",
            message="Server Inventory Core is temporarily unavailable.",
        ) from exc
