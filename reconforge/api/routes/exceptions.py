"""Unified exception queue routes for the local API."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import get_local_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import server_identity_enabled
from reconforge.auth.field_access import project_exception
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.platform.common import PlatformError
from reconforge.platform.exceptions import ExceptionQueueService

router = APIRouter(prefix="/exceptions", tags=["exceptions"])

ExceptionsRead = Annotated[LocalUser, Depends(require_any_permission({"exceptions.read", "exceptions.manage"}))]
ExceptionsManage = Annotated[LocalUser, Depends(require_permission("exceptions.manage"))]


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str


class StatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


def _project_exception(value: Mapping[str, object]) -> dict[str, object]:
    return project_exception(value).visible


def _project_exceptions(values: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [_project_exception(value) for value in values]


def _local_connection(request: Request, connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if server_identity_enabled(request):
        raise APIError(
            status_code=501,
            code="exceptions_server_backend_unavailable",
            message="The unified exception queue is not exposed by the PostgreSQL server boundary.",
        )
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="The local exception queue database is not configured.")
    return connection


@router.get("")
def list_exceptions(
    request: Request,
    current_user: ExceptionsRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    period: str = "",
    entity: str = "",
    account: str = "",
    control: str = "",
    risk: str = "",
    owner: str = "",
    status: str = "",
) -> dict[str, object]:
    """List unified DB-backed exceptions."""

    try:
        records = ExceptionQueueService(_local_connection(request, connection)).list(
            period_name=period,
            entity_code=entity,
            account_code=account,
            control_code=control,
            risk_rating=risk,
            owner=owner,
            status=status,
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="exceptions_list_failed", message=str(exc)) from exc
    return {"exceptions": _project_exceptions(records)}


@router.post("/{exception_id}/assign")
def assign_exception(
    exception_id: str,
    request: Request,
    payload: AssignRequest,
    current_user: ExceptionsManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Assign a unified exception."""

    try:
        record = ExceptionQueueService(_local_connection(request, connection)).assign(
            exception_id, owner=payload.owner, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="exception_assign_failed", message=str(exc)) from exc
    return {"exception": _project_exception(record)}


@router.post("/{exception_id}/status")
def set_exception_status(
    exception_id: str,
    request: Request,
    payload: StatusRequest,
    current_user: ExceptionsManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Set a unified exception status."""

    try:
        record = ExceptionQueueService(_local_connection(request, connection)).set_status(
            exception_id, status=payload.status, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="exception_status_failed", message=str(exc)) from exc
    return {"exception": _project_exception(record)}
