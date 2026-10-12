"""Request-scoped PostgreSQL Inventory Valuation operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from fastapi import Request

from reconforge.api.errors import APIError
from reconforge.api.server_identity import RequestExecutionScope, request_execution_scope
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresTenantBoundary,
    PostgresUnavailableError,
)
from reconforge.infrastructure.postgres_inventory_valuation import (
    PostgresInventoryValuationError,
    PostgresInventoryValuationRepository,
)
from reconforge.infrastructure.postgres_inventory_valuation_reversal import (
    PostgresInventoryValuationReversalError,
    PostgresInventoryValuationReversalRepository,
)
from reconforge.platform.common import PlatformError
from reconforge.platform.inventory_values import code

T = TypeVar("T")
InventoryValuationObject = Literal["inventory_movement", "valuation_document", "valuation_reversal"]


@dataclass(frozen=True)
class InventoryValuationExecutionScope:
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


ValuationOperation = Callable[[PostgresInventoryValuationRepository, InventoryValuationExecutionScope], T]
ReversalOperation = Callable[
    [PostgresInventoryValuationReversalRepository, InventoryValuationExecutionScope], T
]


def get_postgres_inventory_valuation_factory(request: Request) -> PostgresConnectionFactory | None:
    value = getattr(request.app.state, "postgres_inventory_valuation_factory", None)
    return value if isinstance(value, PostgresConnectionFactory) else None


def server_inventory_valuation_enabled(request: Request) -> bool:
    return get_postgres_inventory_valuation_factory(request) is not None


def _row_value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, Mapping) else row[index]


def _scope_codes(
    connection: Any,
    scope: RequestExecutionScope,
    *,
    organization_code: str = "",
    entity_code: str = "",
) -> tuple[str, str]:
    bound_organization = organization_code
    bound_entity = entity_code
    if scope.organization_id is not None:
        organization = connection.execute(
            "SELECT id,organization_code FROM reconforge.organizations WHERE tenant_id=%s AND id=%s",
            (scope.tenant_id, scope.organization_id),
        ).fetchone()
        if organization is None:
            raise PlatformError("Authorized inventory valuation organization was not found.")
        expected_code = str(_row_value(organization, "organization_code", 1))
        linked = connection.execute(
            "SELECT 1 FROM reconforge.master_data_workspace_organizations WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s",
            (scope.tenant_id, scope.workspace_id, scope.organization_id),
        ).fetchone()
        if linked is None:
            raise PlatformError("Authorized inventory valuation organization is not linked to the workspace.")
        if organization_code and code(organization_code, "Organization code") != expected_code:
            raise APIError(status_code=403, code="organization_scope_denied", message="Organization scope is not authorized.")
        bound_organization = expected_code
    if scope.legal_entity_id is not None:
        entity = connection.execute(
            "SELECT id,entity_code FROM reconforge.legal_entities WHERE tenant_id=%s AND organization_id=%s AND id=%s",
            (scope.tenant_id, scope.organization_id, scope.legal_entity_id),
        ).fetchone()
        if entity is None:
            raise PlatformError("Authorized inventory valuation legal entity was not found.")
        expected_code = str(_row_value(entity, "entity_code", 1))
        if entity_code and code(entity_code, "Entity code") != expected_code:
            raise APIError(status_code=403, code="entity_scope_denied", message="Legal-entity scope is not authorized.")
        bound_entity = expected_code
    return bound_organization, bound_entity


def _validate_object_scope(connection: Any, scope: RequestExecutionScope, kind: InventoryValuationObject, object_id: str) -> None:
    if kind == "inventory_movement":
        row = connection.execute(
            "SELECT workspace_id,organization_id,legal_entity_id FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s",
            (scope.tenant_id, object_id),
        ).fetchone()
    elif kind == "valuation_document":
        row = connection.execute(
            "SELECT workspace_id,organization_id,legal_entity_id FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND id=%s",
            (scope.tenant_id, object_id),
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT workspace_id,organization_id,legal_entity_id FROM reconforge.inventory_valuation_reversals WHERE tenant_id=%s AND id=%s",
            (scope.tenant_id, object_id),
        ).fetchone()
    if row is None:
        return
    if str(_row_value(row, "workspace_id", 0)) != scope.workspace_id:
        raise APIError(status_code=403, code="workspace_scope_denied", message="Workspace scope is not authorized.")
    if scope.organization_id is not None and str(_row_value(row, "organization_id", 1) or "") != scope.organization_id:
        raise APIError(status_code=403, code="organization_scope_denied", message="Organization scope is not authorized.")
    if scope.legal_entity_id is not None and str(_row_value(row, "legal_entity_id", 2) or "") != scope.legal_entity_id:
        raise APIError(status_code=403, code="entity_scope_denied", message="Entity scope is not authorized.")


def _run(
    request: Request,
    operation: ValuationOperation[T],
    *,
    organization_code: str = "",
    entity_code: str = "",
    object_refs: tuple[tuple[InventoryValuationObject, str], ...] = (),
) -> T:
    factory = get_postgres_inventory_valuation_factory(request)
    if factory is None:
        raise APIError(status_code=500, code="inventory_valuation_backend_not_configured", message="Server Inventory Valuation backend is not configured.")
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            bound_organization, bound_entity = _scope_codes(
                connection, scope, organization_code=organization_code, entity_code=entity_code
            )
            for kind, object_id in object_refs:
                _validate_object_scope(connection, scope, kind, object_id)
            bound_scope = InventoryValuationExecutionScope(scope, bound_organization, bound_entity)
            return operation(PostgresInventoryValuationRepository(connection, scope.tenant_id), bound_scope)
    except APIError:
        raise
    except PlatformError as exc:
        raise APIError(status_code=400, code="inventory_valuation_request_invalid", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(status_code=503, code="inventory_valuation_unavailable", message="Server Inventory Valuation is temporarily unavailable.") from exc
    except PostgresInventoryValuationError as exc:
        raise APIError(status_code=503, code="inventory_valuation_unavailable", message="Server Inventory Valuation is temporarily unavailable.") from exc
    except Exception as exc:
        raise APIError(status_code=503, code="inventory_valuation_unavailable", message="Server Inventory Valuation is temporarily unavailable.") from exc


def _run_reversal(
    request: Request,
    operation: ReversalOperation[T],
    *,
    object_refs: tuple[tuple[InventoryValuationObject, str], ...] = (),
) -> T:
    factory = get_postgres_inventory_valuation_factory(request)
    if factory is None:
        raise APIError(status_code=500, code="inventory_valuation_backend_not_configured", message="Server Inventory Valuation backend is not configured.")
    scope = request_execution_scope(request)
    try:
        with PostgresTenantBoundary(factory).transaction(
            scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.legal_entity_id,
        ) as connection:
            bound_organization, bound_entity = _scope_codes(connection, scope)
            for kind, object_id in object_refs:
                _validate_object_scope(connection, scope, kind, object_id)
            bound_scope = InventoryValuationExecutionScope(scope, bound_organization, bound_entity)
            return operation(PostgresInventoryValuationReversalRepository(connection, scope.tenant_id), bound_scope)
    except APIError:
        raise
    except PlatformError as exc:
        raise APIError(status_code=400, code="inventory_valuation_reversal_request_invalid", message=str(exc)) from exc
    except (PostgresConfigurationError, PostgresUnavailableError) as exc:
        raise APIError(status_code=503, code="inventory_valuation_reversal_unavailable", message="Server Inventory Valuation Reversal is temporarily unavailable.") from exc
    except PostgresInventoryValuationReversalError as exc:
        raise APIError(status_code=503, code="inventory_valuation_reversal_unavailable", message="Server Inventory Valuation Reversal is temporarily unavailable.") from exc
    except Exception as exc:
        raise APIError(status_code=503, code="inventory_valuation_reversal_unavailable", message="Server Inventory Valuation Reversal is temporarily unavailable.") from exc


__all__ = [
    "InventoryValuationExecutionScope",
    "InventoryValuationObject",
    "_run",
    "_run_reversal",
    "server_inventory_valuation_enabled",
]
