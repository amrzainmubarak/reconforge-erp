"""Authenticated routes for governed local organization master data."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.platform.common import PlatformError
from reconforge.platform.master_data import DEFAULT_LIST_LIMIT, MasterDataService

router = APIRouter(prefix="/master-data", tags=["master-data"])
MAX_API_LIST_LIMIT = 1_000

MasterDataRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"master_data.read", "master_data.manage"})),
]
MasterDataManage = Annotated[LocalUser, Depends(require_permission("master_data.manage"))]
PageLimit = Annotated[int, Query(ge=1, le=MAX_API_LIST_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]


class CurrencyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=200)
    minor_units: int = Field(default=2, ge=0, le=6)
    active: bool = True


class OrganizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    active: bool = True


class LegalEntityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_code: str = Field(min_length=1, max_length=64)
    entity_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    currency_code: str = Field(min_length=1, max_length=16)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    active: bool = True


class BranchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_code: str = Field(min_length=1, max_length=64)
    branch_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    entity_code: str = Field(default="", max_length=64)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    active: bool = True


class PeriodRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    start_date: str = Field(min_length=10, max_length=10)
    end_date: str = Field(min_length=10, max_length=10)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    fiscal_year: int | None = Field(default=None, ge=1900, le=9999)
    period_number: int | None = Field(default=None, ge=1, le=999)


class PeriodStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=32)
    reason: str = Field(default="", max_length=500)


def _api_error(code: str, exc: Exception) -> APIError:
    return APIError(status_code=400, code=code, message=str(exc))


def _list_response(
    key: str,
    records: list[dict[str, object]],
    *,
    limit: int,
    offset: int,
) -> dict[str, object]:
    return {
        key: records,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(records),
        },
    }


@router.get("/summary")
def summary(
    current_user: MasterDataRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    """Return bounded master-data counts for one workspace."""

    try:
        result = MasterDataService(connection).summary(workspace=workspace, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("master_data_summary_failed", exc) from exc
    return {"summary": result.to_dict()}


@router.get("/snapshot")
def snapshot(
    current_user: MasterDataRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    """Return the versioned, path-free organization master-data contract."""

    try:
        return MasterDataService(connection).snapshot(workspace=workspace, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("master_data_snapshot_failed", exc) from exc


@router.get("/currencies")
def list_currencies(
    current_user: MasterDataRead,
    connection: sqlite3.Connection = Depends(get_db),
    active_only: bool = False,
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List governed currency references; no exchange-rate feed is implied."""

    try:
        records = MasterDataService(connection).list_currencies(
            active_only=active_only,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("currencies_list_failed", exc) from exc
    return _list_response("currencies", records, limit=limit, offset=offset)


@router.post("/currencies")
def upsert_currency(
    payload: CurrencyRequest,
    current_user: MasterDataManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Create or update one local currency reference."""

    try:
        record = MasterDataService(connection).upsert_currency(
            code=payload.code,
            name=payload.name,
            minor_units=payload.minor_units,
            active=payload.active,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("currency_save_failed", exc) from exc
    return {"currency": record}


@router.get("/organizations")
def list_organizations(
    current_user: MasterDataRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List organizations in one workspace."""

    try:
        records = MasterDataService(connection).list_organizations(
            workspace=workspace,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("organizations_list_failed", exc) from exc
    return _list_response("organizations", records, limit=limit, offset=offset)


@router.post("/organizations")
def upsert_organization(
    payload: OrganizationRequest,
    current_user: MasterDataManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Create or update one local organization reference."""

    try:
        record = MasterDataService(connection).upsert_organization(
            organization_code=payload.organization_code,
            name=payload.name,
            workspace=payload.workspace,
            active=payload.active,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("organization_save_failed", exc) from exc
    return {"organization": record}


@router.get("/entities")
def list_legal_entities(
    current_user: MasterDataRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    organization: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List legal-entity references in one workspace."""

    try:
        records = MasterDataService(connection).list_legal_entities(
            workspace=workspace,
            organization_code=organization,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("entities_list_failed", exc) from exc
    return _list_response("entities", records, limit=limit, offset=offset)


@router.post("/entities")
def upsert_legal_entity(
    payload: LegalEntityRequest,
    current_user: MasterDataManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Create or update one local legal-entity reference."""

    try:
        record = MasterDataService(connection).upsert_legal_entity(
            organization_code=payload.organization_code,
            entity_code=payload.entity_code,
            name=payload.name,
            currency_code=payload.currency_code,
            workspace=payload.workspace,
            active=payload.active,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("entity_save_failed", exc) from exc
    return {"entity": record}


@router.get("/branches")
def list_branches(
    current_user: MasterDataRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    organization: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List branch references in one workspace."""

    try:
        records = MasterDataService(connection).list_branches(
            workspace=workspace,
            organization_code=organization,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("branches_list_failed", exc) from exc
    return _list_response("branches", records, limit=limit, offset=offset)


@router.post("/branches")
def upsert_branch(
    payload: BranchRequest,
    current_user: MasterDataManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Create or update one local branch reference."""

    try:
        record = MasterDataService(connection).upsert_branch(
            organization_code=payload.organization_code,
            branch_code=payload.branch_code,
            name=payload.name,
            entity_code=payload.entity_code,
            workspace=payload.workspace,
            active=payload.active,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("branch_save_failed", exc) from exc
    return {"branch": record}


@router.get("/periods")
def list_periods(
    current_user: MasterDataRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List local fiscal-period metadata."""

    try:
        records = MasterDataService(connection).list_periods(
            workspace=workspace,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("periods_list_failed", exc) from exc
    return _list_response("periods", records, limit=limit, offset=offset)


@router.post("/periods")
def upsert_period(
    payload: PeriodRequest,
    current_user: MasterDataManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Create or update one non-overlapping local fiscal period."""

    try:
        record = MasterDataService(connection).upsert_period(
            name=payload.name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            workspace=payload.workspace,
            fiscal_year=payload.fiscal_year,
            period_number=payload.period_number,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("period_save_failed", exc) from exc
    return {"period": record}


@router.post("/periods/{period_id}/status")
def set_period_status(
    period_id: str,
    payload: PeriodStatusRequest,
    current_user: MasterDataManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Transition fiscal-period metadata; this does not post or lock ERP transactions."""

    try:
        record = MasterDataService(connection).set_period_status(
            period_id,
            status=payload.status,
            reason=payload.reason,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("period_status_failed", exc) from exc
    return {"period": record}
