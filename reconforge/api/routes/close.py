"""Close management routes for the local API."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import get_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.platform.close import CloseManagementService
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/close", tags=["close"])

CloseRead = Annotated[LocalUser, Depends(require_any_permission({"close.read", "close.manage"}))]
CloseManage = Annotated[LocalUser, Depends(require_permission("close.manage"))]


class PeriodInitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_name: str
    start_date: str
    end_date: str
    workspace: str = "default"


class TaskStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    blocker_reason: str = ""


class ReopenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


@router.get("/periods")
def periods(current_user: CloseRead, connection: sqlite3.Connection = Depends(get_db)) -> dict[str, object]:
    """List DB-backed close periods."""

    try:
        records = CloseManagementService(connection).list_periods()
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="close_periods_failed", message=str(exc)) from exc
    return {"periods": records}


@router.post("/periods")
def period_init(payload: PeriodInitRequest, current_user: CloseManage, connection: sqlite3.Connection = Depends(get_db)) -> dict[str, object]:
    """Initialize a DB-backed close period."""

    try:
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
    current_user: CloseRead,
    connection: sqlite3.Connection = Depends(get_db),
    period_id: str = "",
    status: str = "",
    owner: str = "",
) -> dict[str, object]:
    """List DB-backed close tasks."""

    try:
        records = CloseManagementService(connection).list_tasks(period_id=period_id, status=status, owner=owner)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="close_tasks_failed", message=str(exc)) from exc
    return {"tasks": records}


@router.post("/tasks/{task_id}/status")
def task_status(task_id: str, payload: TaskStatusRequest, current_user: CloseManage, connection: sqlite3.Connection = Depends(get_db)) -> dict[str, object]:
    """Update a DB-backed close task status."""

    try:
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
def readiness(period_id: str, current_user: CloseRead, connection: sqlite3.Connection = Depends(get_db)) -> dict[str, object]:
    """Return close readiness."""

    try:
        value = CloseManagementService(connection).readiness(period_id=period_id, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="close_readiness_failed", message=str(exc)) from exc
    return {"readiness": value.__dict__}


@router.post("/periods/{period_id}/lock")
def lock_period(period_id: str, current_user: CloseManage, connection: sqlite3.Connection = Depends(get_db)) -> dict[str, object]:
    """Lock a DB-backed close period."""

    try:
        period = CloseManagementService(connection).lock_period(period_id, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="close_lock_failed", message=str(exc)) from exc
    return {"period": period}


@router.post("/periods/{period_id}/reopen")
def reopen_period(period_id: str, payload: ReopenRequest, current_user: CloseManage, connection: sqlite3.Connection = Depends(get_db)) -> dict[str, object]:
    """Reopen a DB-backed close period."""

    try:
        period = CloseManagementService(connection).reopen_period(period_id, reason=payload.reason, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="close_reopen_failed", message=str(exc)) from exc
    return {"period": period}
