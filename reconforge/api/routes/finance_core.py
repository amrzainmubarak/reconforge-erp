"""Authenticated routes for the local finance-core control ledger."""

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
from reconforge.platform.finance_core import DEFAULT_LIST_LIMIT, FinanceCoreService

router = APIRouter(prefix="/finance-core", tags=["finance-core"])
MAX_API_LIST_LIMIT = 1_000

FinanceRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"finance_core.read", "finance_core.manage", "finance_core.validate"})),
]
FinanceManage = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]
FinanceValidate = Annotated[LocalUser, Depends(require_permission("finance_core.validate"))]
PageLimit = Annotated[int, Query(ge=1, le=MAX_API_LIST_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]


class ChartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    organization_code: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=500)
    active: bool = True


class AccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    chart_code: str = Field(default="DEFAULT", min_length=1, max_length=64)
    parent_account_code: str = Field(default="", max_length=64)
    account_type: str = Field(default="Asset", min_length=1, max_length=40)
    normal_balance: str = Field(default="Debit", min_length=1, max_length=16)
    allow_posting: bool = True
    allow_manual_posting: bool = True
    reconciliation_required: bool = False
    active: bool = True
    description: str = Field(default="", max_length=500)


class DimensionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    organization_code: str = Field(default="", max_length=64)
    dimension_type: str = Field(default="Custom", min_length=1, max_length=40)
    required_on_entries: bool = False
    active: bool = True


class DimensionValueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_code: str = Field(min_length=1, max_length=64)
    value_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    active: bool = True


class JournalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    journal_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    organization_code: str = Field(min_length=1, max_length=64)
    currency_code: str = Field(min_length=3, max_length=3)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    chart_code: str = Field(default="DEFAULT", min_length=1, max_length=64)
    journal_type: str = Field(default="General", min_length=1, max_length=40)
    active: bool = True


class LedgerLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_code: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    debit: str = Field(default="0", min_length=1, max_length=64)
    credit: str = Field(default="0", min_length=1, max_length=64)
    dimensions: dict[str, str] = Field(default_factory=dict)


class LedgerEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_number: str = Field(min_length=1, max_length=64)
    organization_code: str = Field(min_length=1, max_length=64)
    entity_code: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    journal_code: str = Field(min_length=1, max_length=64)
    posting_date: str = Field(min_length=10, max_length=10)
    description: str = Field(min_length=1, max_length=500)
    lines: list[LedgerLineRequest] = Field(min_length=2, max_length=1_000)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    external_reference: str = Field(default="", max_length=160)
    source_type: str = Field(default="Manual", min_length=1, max_length=40)


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


def _error(code: str, exc: Exception, *, status_code: int = 400) -> APIError:
    return APIError(status_code=status_code, code=code, message=str(exc))


def _list_response(
    key: str,
    records: list[dict[str, object]],
    *,
    limit: int,
    offset: int,
) -> dict[str, object]:
    return {key: records, "pagination": {"limit": limit, "offset": offset, "returned": len(records)}}


@router.get("/summary")
def summary(
    current_user: FinanceRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    try:
        result = FinanceCoreService(connection).summary(workspace=workspace, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_core_summary_failed", exc) from exc
    return {"summary": result.to_dict()}


@router.get("/snapshot")
def snapshot(
    current_user: FinanceRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    try:
        return FinanceCoreService(connection).snapshot(workspace=workspace, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_core_snapshot_failed", exc) from exc


@router.get("/charts")
def list_charts(
    current_user: FinanceRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = FinanceCoreService(connection).list_charts(
            workspace=workspace, limit=limit, offset=offset, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_charts_list_failed", exc) from exc
    return _list_response("charts", records, limit=limit, offset=offset)


@router.post("/charts")
def upsert_chart(
    payload: ChartRequest,
    current_user: FinanceManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = FinanceCoreService(connection).upsert_chart(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_chart_save_failed", exc) from exc
    return {"chart": record}


@router.get("/accounts")
def list_accounts(
    current_user: FinanceRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    chart: str = "",
    active_only: bool = False,
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = FinanceCoreService(connection).list_accounts(
            workspace=workspace,
            chart_code=chart,
            active_only=active_only,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_accounts_list_failed", exc) from exc
    return _list_response("accounts", records, limit=limit, offset=offset)


@router.post("/accounts")
def upsert_account(
    payload: AccountRequest,
    current_user: FinanceManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = FinanceCoreService(connection).upsert_account(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_account_save_failed", exc) from exc
    return {"account": record}


@router.get("/dimensions")
def list_dimensions(
    current_user: FinanceRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = FinanceCoreService(connection).list_dimensions(
            workspace=workspace, limit=limit, offset=offset, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_dimensions_list_failed", exc) from exc
    return _list_response("dimensions", records, limit=limit, offset=offset)


@router.post("/dimensions")
def upsert_dimension(
    payload: DimensionRequest,
    current_user: FinanceManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = FinanceCoreService(connection).upsert_dimension(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_dimension_save_failed", exc) from exc
    return {"dimension": record}


@router.get("/dimension-values")
def list_dimension_values(
    current_user: FinanceRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    dimension: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = FinanceCoreService(connection).list_dimension_values(
            workspace=workspace,
            dimension_code=dimension,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_dimension_values_list_failed", exc) from exc
    return _list_response("dimension_values", records, limit=limit, offset=offset)


@router.post("/dimension-values")
def upsert_dimension_value(
    payload: DimensionValueRequest,
    current_user: FinanceManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = FinanceCoreService(connection).upsert_dimension_value(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_dimension_value_save_failed", exc) from exc
    return {"dimension_value": record}


@router.get("/journals")
def list_journals(
    current_user: FinanceRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    organization: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = FinanceCoreService(connection).list_journals(
            workspace=workspace,
            organization_code=organization,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_journals_list_failed", exc) from exc
    return _list_response("journals", records, limit=limit, offset=offset)


@router.post("/journals")
def upsert_journal(
    payload: JournalRequest,
    current_user: FinanceManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = FinanceCoreService(connection).upsert_journal(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_journal_save_failed", exc) from exc
    return {"journal": record}


@router.get("/trial-balance")
def trial_balance(
    period_id: str,
    organization: str,
    entity: str,
    current_user: FinanceRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
) -> dict[str, object]:
    try:
        return FinanceCoreService(connection).trial_balance(
            period_id=period_id,
            organization_code=organization,
            entity_code=entity,
            workspace=workspace,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_trial_balance_failed", exc) from exc


@router.get("/entries")
def list_entries(
    current_user: FinanceRead,
    connection: sqlite3.Connection = Depends(get_db),
    workspace: str = "default",
    organization: str = "",
    entity: str = "",
    period_id: str = "",
    status: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    try:
        records = FinanceCoreService(connection).list_entries(
            workspace=workspace,
            organization_code=organization,
            entity_code=entity,
            period_id=period_id,
            status=status,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_entries_list_failed", exc) from exc
    return _list_response("entries", records, limit=limit, offset=offset)


@router.post("/entries")
def create_entry(
    payload: LedgerEntryRequest,
    current_user: FinanceManage,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        values = payload.model_dump()
        record = FinanceCoreService(connection).create_entry(**values, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_entry_save_failed", exc) from exc
    return {"entry": record}


@router.get("/entries/{entry_id}")
def get_entry(
    entry_id: str,
    current_user: FinanceRead,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = FinanceCoreService(connection).get_entry(entry_id, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_entry_not_found", exc, status_code=404) from exc
    return {"entry": record}


@router.post("/entries/{entry_id}/validate")
def validate_entry(
    entry_id: str,
    payload: ReasonRequest,
    current_user: FinanceValidate,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = FinanceCoreService(connection).validate_entry(
            entry_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_entry_validate_failed", exc) from exc
    return {"entry": record}


@router.post("/entries/{entry_id}/void")
def void_entry(
    entry_id: str,
    payload: ReasonRequest,
    current_user: FinanceValidate,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    try:
        record = FinanceCoreService(connection).void_entry(
            entry_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_entry_void_failed", exc) from exc
    return {"entry": record}
