"""Authenticated local API access to replay-verifiable manufacturing evidence."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi import Path as FastAPIPath
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import (
    enforce_server_scoped_permission,
    enforce_server_scoped_permissions,
    get_local_db,
    require_any_permission,
    require_permission,
)
from reconforge.api.errors import APIError
from reconforge.api.server_identity import RequestExecutionScope, request_execution_scope, server_identity_enabled
from reconforge.api.server_manufacturing_cost_control import (
    execute_postgres_manufacturing_cost_control,
    server_manufacturing_cost_control_enabled,
)
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres import PostgresConfigurationError, validate_workspace_id
from reconforge.infrastructure.sqlite_manufacturing_cost_control import (
    ManufacturingCostControlPersistenceError,
    SQLiteManufacturingCostControlRepository,
)

router = APIRouter(prefix="/manufacturing", tags=["manufacturing-cost-control"])
ManufacturingRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"finance_core.read", "finance_core.manage", "finance_core.validate"})),
]
ManufacturingManage = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]


class ManufacturingCostControlPersistenceRequest(BaseModel):
    """One closed manufacturing report to persist in local evidence storage."""

    model_config = ConfigDict(extra="forbid", strict=True)

    report: dict[str, object]
    workspace: str | None = Field(default=None, min_length=1, max_length=120)


def _repository(request: Request, connection: sqlite3.Connection | None) -> SQLiteManufacturingCostControlRepository:
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="Local database is not configured.")
    return SQLiteManufacturingCostControlRepository(connection)


def _server_scope(
    request: Request,
    requested_workspace: str | None,
    *,
    permission: str | None = None,
    permissions: frozenset[str] | None = None,
) -> RequestExecutionScope:
    if not server_identity_enabled(request):
        raise APIError(status_code=500, code="server_scope_unavailable", message="Server scope is unavailable.")
    scope = request_execution_scope(request)
    if requested_workspace is not None:
        try:
            normalized_workspace = validate_workspace_id(requested_workspace)
        except PostgresConfigurationError as exc:
            raise APIError(status_code=400, code="invalid_execution_scope", message=str(exc)) from exc
        if normalized_workspace != scope.workspace_id:
            raise APIError(status_code=403, code="workspace_scope_denied", message="Workspace scope is not authorized.")
    if permission is not None:
        enforce_server_scoped_permission(
            request,
            permission=permission,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            organization_id=scope.organization_id,
            entity_id=scope.legal_entity_id,
        )
    elif permissions is not None:
        enforce_server_scoped_permissions(
            request,
            permissions=permissions,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            organization_id=scope.organization_id,
            entity_id=scope.legal_entity_id,
        )
    return scope


def _persistence_error(exc: ValueError) -> APIError:
    status = 409 if "conflicts" in str(exc) else 400
    return APIError(status_code=status, code="manufacturing_cost_control_persistence_failed", message=str(exc))


@router.post("/cost-controls")
def persist_manufacturing_cost_control(
    request: Request,
    payload: ManufacturingCostControlPersistenceRequest,
    current_user: ManufacturingManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Persist one verified report; this route never posts or contacts a provider."""

    if server_identity_enabled(request):
        if not server_manufacturing_cost_control_enabled(request):
            raise APIError(
                status_code=503,
                code="manufacturing_cost_control_backend_not_configured",
                message="Server manufacturing cost-control persistence is not configured.",
            )
        scope = _server_scope(request, payload.workspace, permission="finance_core.manage")

        def persist(repository: object, tenant_id: str, workspace_id: str) -> dict[str, object]:
            return repository.put_payload(  # type: ignore[attr-defined]
                payload.report,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                actor_label=current_user.username,
            )

        stored = execute_postgres_manufacturing_cost_control(request, persist)
        return {
            "manufacturing_cost_control": stored,
            "source": {"kind": "postgresql-manufacturing-cost-control", "server_mode": True},
            "network_dispatch": "disabled",
            "workspace": scope.workspace_id,
        }
    try:
        stored = _repository(request, connection).put_payload(
            payload.report,
            workspace=payload.workspace or "default",
            actor_label=current_user.username,
        )
    except ManufacturingCostControlPersistenceError as exc:
        raise _persistence_error(exc) from exc
    return {
        "manufacturing_cost_control": stored,
        "source": {"kind": "sqlite-manufacturing-cost-control", "server_mode": False},
        "network_dispatch": "disabled",
    }


@router.get("/cost-controls")
def list_manufacturing_cost_controls(
    request: Request,
    current_user: ManufacturingRead,
    workspace: str | None = Query(default=None, min_length=1, max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10_000_000),
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """List immutable manufacturing evidence within one workspace."""

    if server_identity_enabled(request):
        if not server_manufacturing_cost_control_enabled(request):
            raise APIError(
                status_code=503,
                code="manufacturing_cost_control_backend_not_configured",
                message="Server manufacturing cost-control persistence is not configured.",
            )
        scope = _server_scope(
            request,
            workspace,
            permissions=frozenset({"finance_core.read", "finance_core.manage", "finance_core.validate"}),
        )

        def read(repository: object, tenant_id: str, workspace_id: str) -> tuple[dict[str, object], ...]:
            return repository.list(  # type: ignore[attr-defined]
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                limit=limit,
                offset=offset,
            )

        records = execute_postgres_manufacturing_cost_control(request, read)
        return {
            "manufacturing_cost_controls": records,
            "workspace": scope.workspace_id,
            "limit": limit,
            "offset": offset,
            "source": {"kind": "postgresql-manufacturing-cost-control", "server_mode": True},
        }
    try:
        resolved_workspace = workspace or "default"
        records = _repository(request, connection).list(
            workspace=resolved_workspace,
            limit=limit,
            offset=offset,
        )
    except ManufacturingCostControlPersistenceError as exc:
        raise _persistence_error(exc) from exc
    return {
        "manufacturing_cost_controls": records,
        "workspace": resolved_workspace,
        "limit": limit,
        "offset": offset,
        "source": {"kind": "sqlite-manufacturing-cost-control", "server_mode": False},
    }


@router.get("/cost-controls/{decision_digest}")
def get_manufacturing_cost_control(
    request: Request,
    current_user: ManufacturingRead,
    decision_digest: str = FastAPIPath(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
    workspace: str | None = Query(default=None, min_length=1, max_length=120),
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Read one replay-verified manufacturing report by decision digest."""

    if server_identity_enabled(request):
        if not server_manufacturing_cost_control_enabled(request):
            raise APIError(
                status_code=503,
                code="manufacturing_cost_control_backend_not_configured",
                message="Server manufacturing cost-control persistence is not configured.",
            )
        _server_scope(
            request,
            workspace,
            permissions=frozenset({"finance_core.read", "finance_core.manage", "finance_core.validate"}),
        )

        def read(repository: object, tenant_id: str, workspace_id: str) -> dict[str, object] | None:
            return repository.get(  # type: ignore[attr-defined]
                decision_digest=decision_digest,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )

        record = execute_postgres_manufacturing_cost_control(request, read)
        if record is None:
            raise APIError(
                status_code=404,
                code="manufacturing_cost_control_not_found",
                message="Manufacturing cost-control evidence was not found.",
            )
        return {
            "manufacturing_cost_control": record,
            "source": {"kind": "postgresql-manufacturing-cost-control", "server_mode": True},
        }
    try:
        record = _repository(request, connection).get(
            decision_digest=decision_digest,
            workspace=workspace or "default",
        )
    except ManufacturingCostControlPersistenceError as exc:
        raise _persistence_error(exc) from exc
    if record is None:
        raise APIError(
            status_code=404,
            code="manufacturing_cost_control_not_found",
            message="Manufacturing cost-control evidence was not found.",
        )
    return {
        "manufacturing_cost_control": record,
        "source": {"kind": "sqlite-manufacturing-cost-control", "server_mode": False},
    }


__all__ = ["router"]
