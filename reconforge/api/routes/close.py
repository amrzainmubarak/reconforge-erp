"""Close management routes for the local API."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import (
    enforce_server_scoped_permission,
    get_local_db,
    require_any_permission,
    require_permission,
)
from reconforge.api.errors import APIError
from reconforge.api.server_close import execute_postgres_close, server_close_enabled
from reconforge.api.server_identity import request_execution_scope
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.infrastructure.postgres_close import POSTGRES_DEFAULT_CLOSE_TASKS, PostgresCloseRepository
from reconforge.platform.close import CloseManagementService
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/close", tags=["close"])

CloseRead = Annotated[LocalUser, Depends(require_any_permission({"close.read", "close.manage"}))]
CloseManage = Annotated[LocalUser, Depends(require_permission("close.manage"))]


class PeriodInitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_name: str = ""
    start_date: str = ""
    end_date: str = ""
    workspace: str = "default"
    fiscal_period_id: str = ""
    organization_code: str = ""


class TaskStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    blocker_reason: str = ""


class ReopenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


def _server_workspace(workspace: str) -> None:
    if workspace.strip().casefold() not in {"", "default"}:
        raise APIError(
            status_code=400,
            code="server_workspace_unsupported",
            message="The PostgreSQL server close boundary is tenant-scoped and does not support workspaces yet.",
        )


def _server_id(*parts: object) -> str:
    digest = hashlib.sha256("|".join(str(part).strip().casefold() for part in parts).encode("utf-8")).hexdigest()
    return f"close-{digest[:48]}"


@router.get("/periods")
def periods(
    request: Request,
    current_user: CloseRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """List close periods from the configured persistence boundary."""

    if server_close_enabled(request):
        records = execute_postgres_close(request, lambda repository, tenant: repository.list_periods(tenant_id=tenant))
        return {"periods": records, "source": {"kind": "postgresql-close-control", "server_mode": True}}

    try:
        if connection is None:
            raise APIError(
                status_code=500, code="local_database_not_configured", message="Local close database is not configured."
            )
        records = CloseManagementService(connection).list_periods()
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="close_periods_failed", message=str(exc)) from exc
    return {"periods": records}


@router.post("/periods")
def period_init(
    request: Request,
    payload: PeriodInitRequest,
    current_user: CloseManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Initialize a close period in the configured persistence boundary."""

    if server_close_enabled(request):
        _server_workspace(payload.workspace)
        scope = request_execution_scope(request)
        enforce_server_scoped_permission(
            request,
            permission="close.manage",
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
        )
        if not payload.fiscal_period_id.strip() or not payload.organization_code.strip():
            raise APIError(
                status_code=400,
                code="close_scope_required",
                message="fiscal_period_id and organization_code are required in PostgreSQL server mode.",
            )

        def operation(repository: PostgresCloseRepository, tenant: str) -> dict[str, object]:
            organization = repository.organization_by_code(
                tenant_id=tenant, organization_code=payload.organization_code
            )
            period = repository.create_period(
                tenant_id=tenant,
                period_id=_server_id(tenant, organization["id"], payload.fiscal_period_id),
                fiscal_period_id=payload.fiscal_period_id,
                organization_id=str(organization["id"]),
                organization_code=payload.organization_code,
                expected_start_date=payload.start_date,
                expected_end_date=payload.end_date,
                actor_id=current_user.id,
                request_id=str(getattr(request.state, "request_id", "")),
            )
            for task_code, name, category, risk in POSTGRES_DEFAULT_CLOSE_TASKS:
                repository.upsert_task(
                    tenant_id=tenant,
                    task_id=_server_id(str(period["id"]), task_code),
                    close_period_id=str(period["id"]),
                    task_code=task_code,
                    name=name,
                    category=category,
                    risk_rating=risk,
                    actor_id=current_user.id,
                    request_id=str(getattr(request.state, "request_id", "")),
                )
            return repository.get_period(tenant_id=tenant, period_id=str(period["id"]))

        period = execute_postgres_close(request, operation)
        return {"period": period, "source": {"kind": "postgresql-close-control", "server_mode": True}}

    try:
        if connection is None:
            raise APIError(
                status_code=500, code="local_database_not_configured", message="Local close database is not configured."
            )
        period = CloseManagementService(connection).period_init(
            period_name=payload.period_name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            workspace=payload.workspace,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="close_period_init_failed", message=str(exc)) from exc
    return {"period": period}


@router.get("/tasks")
def tasks(
    request: Request,
    current_user: CloseRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    period_id: str = "",
    status: str = "",
    owner: str = "",
) -> dict[str, object]:
    """List close tasks from the configured persistence boundary."""

    if server_close_enabled(request):
        records = execute_postgres_close(
            request,
            lambda repository, tenant: repository.list_tasks(
                tenant_id=tenant,
                close_period_id=period_id,
                status=status,
                owner_user_id=owner,
            ),
        )
        return {"tasks": records, "source": {"kind": "postgresql-close-control", "server_mode": True}}

    try:
        if connection is None:
            raise APIError(
                status_code=500, code="local_database_not_configured", message="Local close database is not configured."
            )
        records = CloseManagementService(connection).list_tasks(period_id=period_id, status=status, owner=owner)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="close_tasks_failed", message=str(exc)) from exc
    return {"tasks": records}


@router.post("/tasks/{task_id}/status")
def task_status(
    request: Request,
    task_id: str,
    payload: TaskStatusRequest,
    current_user: CloseManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Update a close task status in the configured persistence boundary."""

    if server_close_enabled(request):
        scope = request_execution_scope(request)
        enforce_server_scoped_permission(
            request,
            permission="close.manage",
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
        )
        task = execute_postgres_close(
            request,
            lambda repository, tenant: repository.set_task_status(
                tenant_id=tenant,
                task_id=task_id,
                status=payload.status,
                blocker_reason=payload.blocker_reason,
                actor_id=current_user.id,
                request_id=str(getattr(request.state, "request_id", "")),
            ),
        )
        return {"task": task, "source": {"kind": "postgresql-close-control", "server_mode": True}}

    try:
        if connection is None:
            raise APIError(
                status_code=500, code="local_database_not_configured", message="Local close database is not configured."
            )
        task = CloseManagementService(connection).task_status(
            task_id=task_id,
            status=payload.status,
            blocker_reason=payload.blocker_reason,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="close_task_status_failed", message=str(exc)) from exc
    return {"task": task}


@router.get("/periods/{period_id}/readiness")
def readiness(
    request: Request,
    period_id: str,
    current_user: CloseRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Return close readiness."""

    if server_close_enabled(request):
        value = execute_postgres_close(
            request, lambda repository, tenant: repository.readiness(tenant_id=tenant, period_id=period_id)
        )
        return {"readiness": value, "source": {"kind": "postgresql-close-control", "server_mode": True}}

    try:
        if connection is None:
            raise APIError(
                status_code=500, code="local_database_not_configured", message="Local close database is not configured."
            )
        readiness_value = CloseManagementService(connection).readiness(
            period_id=period_id, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="close_readiness_failed", message=str(exc)) from exc
    return {"readiness": readiness_value.__dict__}


@router.post("/periods/{period_id}/lock")
def lock_period(
    request: Request,
    period_id: str,
    current_user: CloseManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Lock a close period in the configured close-control boundary."""

    if server_close_enabled(request):
        scope = request_execution_scope(request)
        enforce_server_scoped_permission(
            request,
            permission="close.manage",
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
        )
        period = execute_postgres_close(
            request,
            lambda repository, tenant: repository.set_period_status(
                tenant_id=tenant,
                period_id=period_id,
                status="Locked",
                actor_id=current_user.id,
                request_id=str(getattr(request.state, "request_id", "")),
            ),
        )
        return {"period": period, "source": {"kind": "postgresql-close-control", "server_mode": True}}

    try:
        if connection is None:
            raise APIError(
                status_code=500, code="local_database_not_configured", message="Local close database is not configured."
            )
        period = CloseManagementService(connection).lock_period(period_id, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="close_lock_failed", message=str(exc)) from exc
    return {"period": period}


@router.post("/periods/{period_id}/reopen")
def reopen_period(
    request: Request,
    period_id: str,
    payload: ReopenRequest,
    current_user: CloseManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Reopen a close period in the configured close-control boundary."""

    if server_close_enabled(request):
        scope = request_execution_scope(request)
        enforce_server_scoped_permission(
            request,
            permission="close.manage",
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
        )
        period = execute_postgres_close(
            request,
            lambda repository, tenant: repository.set_period_status(
                tenant_id=tenant,
                period_id=period_id,
                status="Reopened",
                reason=payload.reason,
                actor_id=current_user.id,
                request_id=str(getattr(request.state, "request_id", "")),
            ),
        )
        return {"period": period, "source": {"kind": "postgresql-close-control", "server_mode": True}}

    try:
        if connection is None:
            raise APIError(
                status_code=500, code="local_database_not_configured", message="Local close database is not configured."
            )
        period = CloseManagementService(connection).reopen_period(
            period_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="close_reopen_failed", message=str(exc)) from exc
    return {"period": period}
