"""Unified exception queue routes for the local API."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import get_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
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


@router.get("")
def list_exceptions(
    current_user: ExceptionsRead,
    connection: sqlite3.Connection = Depends(get_db),
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
        records = ExceptionQueueService(connection).list(
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
    return {"exceptions": records}


@router.post("/{exception_id}/assign")
def assign_exception(
    exception_id: str,
    payload: AssignRequest,
    current_user: ExceptionsManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Assign a unified exception."""

    try:
        record = ExceptionQueueService(connection).assign(exception_id, owner=payload.owner, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="exception_assign_failed", message=str(exc)) from exc
    return {"exception": record}


@router.post("/{exception_id}/status")
def set_exception_status(
    exception_id: str,
    payload: StatusRequest,
    current_user: ExceptionsManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Set a unified exception status."""

    try:
        record = ExceptionQueueService(connection).set_status(exception_id, status=payload.status, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="exception_status_failed", message=str(exc)) from exc
    return {"exception": record}
