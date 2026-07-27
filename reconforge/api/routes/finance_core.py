"""Authenticated routes for the local finance-core control ledger."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_local_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_ledger import execute_postgres_ledger, server_ledger_enabled
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.infrastructure.postgres_ledger import (
    LedgerLine,
    PostgresLedgerRepository,
    PostgresLedgerValidationError,
)
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
    organization_code: str = Field(default="", max_length=64)
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
    entity_code: str = Field(default="", max_length=64)
    period_id: str = Field(default="", max_length=160)
    journal_code: str = Field(default="", max_length=64)
    posting_date: str = Field(min_length=10, max_length=10)
    description: str = Field(min_length=1, max_length=500)
    lines: list[LedgerLineRequest] = Field(min_length=2, max_length=1_000)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    external_reference: str = Field(default="", max_length=160)
    source_type: str = Field(default="Manual", min_length=1, max_length=40)
    currency_code: str = Field(default="", max_length=3)


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


def _local_connection(connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if connection is None:
        raise APIError(
            status_code=500,
            code="local_database_not_configured",
            message="The local Finance Core database is not configured for this request.",
        )
    return connection


def _server_unsupported(capability: str) -> APIError:
    return APIError(
        status_code=501,
        code="server_ledger_capability_unavailable",
        message=f"The PostgreSQL server ledger boundary does not support {capability} yet.",
    )


def _server_workspace(workspace: str) -> None:
    if workspace.strip().casefold() not in {"", "default"}:
        raise APIError(
            status_code=400,
            code="server_workspace_unsupported",
            message="The PostgreSQL server ledger boundary is tenant-scoped and does not support workspaces yet.",
        )


def _server_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("|".join(str(part).strip().casefold() for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:48]}"


def _server_account_record(record: dict[str, object]) -> dict[str, object]:
    return {
        **record,
        "source_backend": "postgresql-ledger-control",
        "chart_code": None,
        "workspace": None,
        "allow_posting": True,
        "allow_manual_posting": True,
        "reconciliation_required": False,
        "description": "",
    }


def _server_entry(
    repository: PostgresLedgerRepository,
    tenant_id: str,
    payload: LedgerEntryRequest,
    *,
    actor_id: str,
    request_id: str,
) -> dict[str, object]:
    _server_workspace(payload.workspace)
    if payload.entity_code.strip() or payload.period_id.strip() or payload.journal_code.strip():
        # These fields are part of the local Finance Core contract but are not
        # represented by the bounded PostgreSQL ledger schema.  Rejecting them
        # avoids silently dropping accounting dimensions from a posted entry.
        raise _server_unsupported("legal entities, fiscal periods, and finance journals")
    organization = repository.organization_by_code(
        tenant_id=tenant_id, organization_code=payload.organization_code
    )
    if not bool(organization["active"]):
        raise PostgresLedgerValidationError("Ledger entries require an active organization.")
    currency = payload.currency_code.strip().upper() or str(organization.get("base_currency") or "").upper()
    if not currency:
        raise PostgresLedgerValidationError(
            "currency_code is required when the organization has no configured base currency."
        )
    normalized_lines: list[LedgerLine] = []
    for line_number, line in enumerate(payload.lines, start=1):
        if line.dimensions:
            raise _server_unsupported("accounting dimensions")
        account = repository.account_by_code(
            tenant_id=tenant_id,
            organization_id=str(organization["id"]),
            account_code=line.account_code,
        )
        if not bool(account["active"]):
            raise PostgresLedgerValidationError(f"Line {line_number} requires an active posting account.")
        normalized_lines.append(
            LedgerLine(
                account_id=str(account["id"]),
                debit=line.debit,
                credit=line.credit,
                description=line.description,
                reference="",
            )
        )
    entry_number = payload.entry_number.strip().upper()
    return repository.post_entry(
        tenant_id=tenant_id,
        entry_id=_server_id("entry", tenant_id, organization["id"], entry_number),
        entry_number=entry_number,
        organization_id=str(organization["id"]),
        currency_code=currency,
        posting_date=payload.posting_date,
        description=payload.description,
        lines=normalized_lines,
        actor_id=actor_id,
        request_id=request_id,
        source_type=payload.source_type,
        source_id=payload.external_reference or None,
    )


@router.get("/summary")
def summary(
    request: Request,
    current_user: FinanceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    if server_ledger_enabled(request):
        _server_workspace(workspace)
        server_result = execute_postgres_ledger(request, lambda repository, tenant: repository.summary(tenant_id=tenant))
        return {
            "summary": {
                "workspace": None,
                "accounts": server_result["accounts"],
                "draft_entries": server_result["draft_entries"],
                "posted_entries": server_result["posted_entries"],
                "source": server_result["source"],
                "unsupported_collections": server_result["unsupported_collections"],
            }
        }
    try:
        local_result = FinanceCoreService(_local_connection(connection)).summary(
            workspace=workspace, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_core_summary_failed", exc) from exc
    return {"summary": local_result.to_dict()}


@router.get("/snapshot")
def snapshot(
    request: Request,
    current_user: FinanceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    if server_ledger_enabled(request):
        raise _server_unsupported("the full Finance Core snapshot")
    try:
        return FinanceCoreService(_local_connection(connection)).snapshot(
            workspace=workspace, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_core_snapshot_failed", exc) from exc


@router.get("/charts")
def list_charts(
    request: Request,
    current_user: FinanceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_ledger_enabled(request):
        raise _server_unsupported("charts of accounts")
    try:
        records = FinanceCoreService(_local_connection(connection)).list_charts(
            workspace=workspace, limit=limit, offset=offset, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_charts_list_failed", exc) from exc
    return _list_response("charts", records, limit=limit, offset=offset)


@router.post("/charts")
def upsert_chart(
    request: Request,
    payload: ChartRequest,
    current_user: FinanceManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_ledger_enabled(request):
        raise _server_unsupported("charts of accounts")
    try:
        record = FinanceCoreService(_local_connection(connection)).upsert_chart(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_chart_save_failed", exc) from exc
    return {"chart": record}


@router.get("/accounts")
def list_accounts(
    request: Request,
    current_user: FinanceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    chart: str = "",
    organization: str = "",
    active_only: bool = False,
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_ledger_enabled(request):
        _server_workspace(workspace)
        if chart:
            raise _server_unsupported("chart filtering")

        def operation(repository: PostgresLedgerRepository, tenant: str) -> list[dict[str, object]]:
            organization_id = None
            if organization:
                organization_id = str(
                    repository.organization_by_code(tenant_id=tenant, organization_code=organization)["id"]
                )
            records = repository.list_accounts(tenant_id=tenant, organization_id=organization_id)
            return [_server_account_record(record) for record in records if not active_only or bool(record["active"])]

        records = execute_postgres_ledger(request, operation)
        page = records[offset : offset + limit]
        return _list_response("accounts", page, limit=limit, offset=offset)
    try:
        records = FinanceCoreService(_local_connection(connection)).list_accounts(
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
    request: Request,
    payload: AccountRequest,
    current_user: FinanceManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_ledger_enabled(request):
        _server_workspace(payload.workspace)
        if not payload.organization_code.strip():
            raise APIError(
                status_code=400,
                code="organization_required",
                message="organization_code is required by the PostgreSQL server ledger boundary.",
            )
        if payload.chart_code.strip().upper() != "DEFAULT" or payload.parent_account_code.strip():
            raise _server_unsupported("chart hierarchy")
        if not payload.allow_posting or not payload.allow_manual_posting or payload.reconciliation_required:
            raise _server_unsupported("account posting-policy flags")
        if payload.description.strip():
            raise _server_unsupported("account descriptions")

        def operation(repository: PostgresLedgerRepository, tenant: str) -> dict[str, object]:
            organization = repository.organization_by_code(
                tenant_id=tenant, organization_code=payload.organization_code
            )
            return _server_account_record(
                repository.upsert_account(
                    tenant_id=tenant,
                    organization_id=str(organization["id"]),
                    account_id=_server_id("account", tenant, organization["id"], payload.account_code),
                    account_code=payload.account_code,
                    name=payload.name,
                    account_type=payload.account_type,
                    normal_balance=payload.normal_balance,
                    active=payload.active,
                    actor_id=current_user.id,
                    request_id=str(getattr(request.state, "request_id", "")),
                )
            )

        return {"account": execute_postgres_ledger(request, operation)}
    try:
        values = payload.model_dump()
        values.pop("organization_code", None)
        record = FinanceCoreService(_local_connection(connection)).upsert_account(
            **values, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_account_save_failed", exc) from exc
    return {"account": record}


@router.get("/dimensions")
def list_dimensions(
    request: Request,
    current_user: FinanceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_ledger_enabled(request):
        raise _server_unsupported("accounting dimensions")
    try:
        records = FinanceCoreService(_local_connection(connection)).list_dimensions(
            workspace=workspace, limit=limit, offset=offset, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_dimensions_list_failed", exc) from exc
    return _list_response("dimensions", records, limit=limit, offset=offset)


@router.post("/dimensions")
def upsert_dimension(
    request: Request,
    payload: DimensionRequest,
    current_user: FinanceManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_ledger_enabled(request):
        raise _server_unsupported("accounting dimensions")
    try:
        record = FinanceCoreService(_local_connection(connection)).upsert_dimension(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_dimension_save_failed", exc) from exc
    return {"dimension": record}


@router.get("/dimension-values")
def list_dimension_values(
    request: Request,
    current_user: FinanceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    dimension: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_ledger_enabled(request):
        raise _server_unsupported("accounting dimension values")
    try:
        records = FinanceCoreService(_local_connection(connection)).list_dimension_values(
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
    request: Request,
    payload: DimensionValueRequest,
    current_user: FinanceManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_ledger_enabled(request):
        raise _server_unsupported("accounting dimension values")
    try:
        record = FinanceCoreService(_local_connection(connection)).upsert_dimension_value(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_dimension_value_save_failed", exc) from exc
    return {"dimension_value": record}


@router.get("/journals")
def list_journals(
    request: Request,
    current_user: FinanceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    organization: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_ledger_enabled(request):
        raise _server_unsupported("finance journals")
    try:
        records = FinanceCoreService(_local_connection(connection)).list_journals(
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
    request: Request,
    payload: JournalRequest,
    current_user: FinanceManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_ledger_enabled(request):
        raise _server_unsupported("finance journals")
    try:
        record = FinanceCoreService(_local_connection(connection)).upsert_journal(
            **payload.model_dump(), actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_journal_save_failed", exc) from exc
    return {"journal": record}


@router.get("/trial-balance")
def trial_balance(
    request: Request,
    period_id: str,
    organization: str,
    entity: str,
    current_user: FinanceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    if server_ledger_enabled(request):
        _server_workspace(workspace)
        if entity.strip():
            raise _server_unsupported("legal-entity-scoped trial balance")

        def operation(repository: PostgresLedgerRepository, tenant: str) -> dict[str, object]:
            organization_record = repository.organization_by_code(
                tenant_id=tenant,
                organization_code=organization,
            )
            if not bool(organization_record["active"]):
                raise PostgresLedgerValidationError("Trial balance requires an active organization.")
            return repository.trial_balance(
                tenant_id=tenant,
                organization_id=str(organization_record["id"]),
                organization_code=organization,
                period_id=period_id,
            )

        return execute_postgres_ledger(request, operation)
    try:
        return FinanceCoreService(_local_connection(connection)).trial_balance(
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
    request: Request,
    current_user: FinanceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    organization: str = "",
    entity: str = "",
    period_id: str = "",
    status: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    if server_ledger_enabled(request):
        _server_workspace(workspace)
        if entity or period_id:
            raise _server_unsupported("entity- and fiscal-period-scoped entry filtering")

        def operation(repository: PostgresLedgerRepository, tenant: str) -> list[dict[str, object]]:
            organization_id = None
            if organization:
                organization_record = repository.organization_by_code(
                    tenant_id=tenant, organization_code=organization
                )
                organization_id = str(organization_record["id"])
            return repository.list_entries(
                tenant_id=tenant,
                organization_id=organization_id,
                status=status or None,
                limit=limit,
                offset=offset,
            )

        records = execute_postgres_ledger(request, operation)
        return _list_response("entries", records, limit=limit, offset=offset)
    try:
        records = FinanceCoreService(_local_connection(connection)).list_entries(
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
    request: Request,
    payload: LedgerEntryRequest,
    current_user: FinanceManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_ledger_enabled(request):
        record = execute_postgres_ledger(
            request,
            lambda repository, tenant: _server_entry(
                repository,
                tenant,
                payload,
                actor_id=current_user.id,
                request_id=str(getattr(request.state, "request_id", "")),
            ),
        )
        return {"entry": record}
    try:
        values = payload.model_dump()
        values.pop("currency_code", None)
        record = FinanceCoreService(_local_connection(connection)).create_entry(
            **values, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_entry_save_failed", exc) from exc
    return {"entry": record}


@router.get("/entries/{entry_id}")
def get_entry(
    request: Request,
    entry_id: str,
    current_user: FinanceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_ledger_enabled(request):
        record = execute_postgres_ledger(
            request, lambda repository, tenant: repository.get_entry(tenant_id=tenant, entry_id=entry_id)
        )
        return {"entry": record}
    try:
        record = FinanceCoreService(_local_connection(connection)).get_entry(
            entry_id, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_entry_not_found", exc, status_code=404) from exc
    return {"entry": record}


@router.post("/entries/{entry_id}/validate")
def validate_entry(
    request: Request,
    entry_id: str,
    payload: ReasonRequest,
    current_user: FinanceValidate,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_ledger_enabled(request):
        raise _server_unsupported("draft validation; server entries are posted atomically")
    try:
        record = FinanceCoreService(_local_connection(connection)).validate_entry(
            entry_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_entry_validate_failed", exc) from exc
    return {"entry": record}


@router.post("/entries/{entry_id}/void")
def void_entry(
    request: Request,
    entry_id: str,
    payload: ReasonRequest,
    current_user: FinanceValidate,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    if server_ledger_enabled(request):
        raise _server_unsupported("voiding; server entries are immutable and require reversal support")
    try:
        record = FinanceCoreService(_local_connection(connection)).void_entry(
            entry_id, reason=payload.reason, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _error("finance_entry_void_failed", exc) from exc
    return {"entry": record}
