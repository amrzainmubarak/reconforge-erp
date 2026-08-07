"""Authenticated local API access to replay-verifiable retail evidence."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_local_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import server_identity_enabled
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.sqlite_retail_settlement import (
    RetailSettlementPersistenceError,
    SQLiteRetailSettlementRepository,
)

router = APIRouter(prefix="/retail", tags=["retail-settlement"])
RetailRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"finance_core.read", "finance_core.manage", "finance_core.validate"})),
]
RetailManage = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]


class RetailSettlementPersistenceRequest(BaseModel):
    """One closed report to persist in the local evidence boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)

    report: dict[str, object]
    workspace: str = Field(default="default", min_length=1, max_length=120)


def _local_repository(request: Request, connection: sqlite3.Connection | None) -> SQLiteRetailSettlementRepository:
    if server_identity_enabled(request):
        raise APIError(
            status_code=501,
            code="retail_persistence_server_unsupported",
            message="Retail settlement persistence requires a local SQLite profile until PostgreSQL parity is implemented.",
        )
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="Local database is not configured.")
    return SQLiteRetailSettlementRepository(connection)


def _persistence_error(exc: RetailSettlementPersistenceError) -> APIError:
    status = 409 if "conflicts" in str(exc) else 400
    return APIError(status_code=status, code="retail_settlement_persistence_failed", message=str(exc))


@router.post("/settlements")
def persist_settlement(
    request: Request,
    payload: RetailSettlementPersistenceRequest,
    current_user: RetailManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Persist one verified report; this route never posts or contacts a provider."""

    try:
        stored = _local_repository(request, connection).put_payload(
            payload.report,
            workspace=payload.workspace,
            actor_label=current_user.username,
        )
    except RetailSettlementPersistenceError as exc:
        raise _persistence_error(exc) from exc
    return {
        "settlement": stored,
        "source": {"kind": "sqlite-retail-settlement", "server_mode": False},
        "network_dispatch": "disabled",
    }


@router.get("/settlements")
def list_settlements(
    request: Request,
    current_user: RetailRead,
    workspace: str = Query(default="default", min_length=1, max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10_000_000),
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """List local evidence rows within one workspace."""

    try:
        records = _local_repository(request, connection).list(workspace=workspace, limit=limit, offset=offset)
    except RetailSettlementPersistenceError as exc:
        raise _persistence_error(exc) from exc
    return {
        "settlements": records,
        "workspace": workspace,
        "limit": limit,
        "offset": offset,
        "source": {"kind": "sqlite-retail-settlement", "server_mode": False},
    }


@router.get("/settlements/{decision_digest}")
def get_settlement(
    decision_digest: str,
    request: Request,
    current_user: RetailRead,
    workspace: str = Query(default="default", min_length=1, max_length=120),
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Read one local report by its deterministic decision digest."""

    try:
        record = _local_repository(request, connection).get(
            decision_digest=decision_digest,
            workspace=workspace,
        )
    except RetailSettlementPersistenceError as exc:
        raise _persistence_error(exc) from exc
    if record is None:
        raise APIError(status_code=404, code="retail_settlement_not_found", message="Retail settlement evidence was not found.")
    return {
        "settlement": record,
        "source": {"kind": "sqlite-retail-settlement", "server_mode": False},
    }


__all__ = ["router"]
