"""Account reconciliation routes for the local API."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import (
    enforce_server_scoped_permission,
    enforce_server_scoped_permissions,
    get_local_db,
    require_any_permission,
    require_permission,
)
from reconforge.api.errors import APIError
from reconforge.api.server_accounts import execute_postgres_accounts, server_accounts_enabled
from reconforge.api.server_identity import RequestExecutionScope, request_execution_scope
from reconforge.auth.field_access import project_account_reconciliation
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.platform.accounts import AccountReconciliationService
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/accounts", tags=["accounts"])

AccountRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"accounts.read", "accounts.prepare", "accounts.review", "accounts.complete"})),
]
AccountPrepare = Annotated[LocalUser, Depends(require_permission("accounts.prepare"))]
AccountReview = Annotated[LocalUser, Depends(require_permission("accounts.review"))]
AccountComplete = Annotated[LocalUser, Depends(require_permission("accounts.complete"))]


def _project_record(value: dict[str, object]) -> dict[str, object]:
    return project_account_reconciliation(value).visible


def _project_records(values: list[dict[str, object]]) -> list[dict[str, object]]:
    return [_project_record(value) for value in values]


class CreateReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_name: str
    entity_code: str
    account_code: str
    account_name: str = ""
    workspace: str = "default"
    balance: Decimal = Decimal("0")
    owner: str = ""
    preparer: str = ""
    reviewer: str = ""
    risk_rating: str = "medium"
    materiality_threshold: Decimal = Decimal("0")


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_note: str = ""
    reviewer: str = ""


def _local_connection(connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if connection is None:
        raise APIError(
            status_code=500,
            code="local_database_not_configured",
            message="The local account-reconciliation database is not configured for this request.",
        )
    return connection


def _server_scope(
    request: Request,
    *,
    permissions: frozenset[str],
    amount: Decimal | None = None,
) -> RequestExecutionScope:
    scope = request_execution_scope(request)
    if len(permissions) == 1:
        enforce_server_scoped_permission(
            request,
            permission=next(iter(permissions)),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            organization_id=scope.organization_id,
            entity_id=scope.legal_entity_id,
            amount=amount,
        )
    else:
        enforce_server_scoped_permissions(
            request,
            permissions=permissions,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            organization_id=scope.organization_id,
            entity_id=scope.legal_entity_id,
            amount=amount,
        )
    return scope


@router.get("/reconciliations")
def list_reconciliations(
    request: Request,
    current_user: AccountRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    status: str = "",
    owner: str = "",
    period: str = "",
    entity: str = "",
    risk: str = "",
) -> dict[str, object]:
    """List DB-backed account reconciliation records."""

    if server_accounts_enabled(request):
        _server_scope(
            request,
            permissions=frozenset({"accounts.read", "accounts.prepare", "accounts.review", "accounts.complete"}),
        )
        records = execute_postgres_accounts(
            request,
            lambda repository, _tenant: repository.list_reconciliations(
                status=status, owner=owner, period_name=period, entity_code=entity, risk_rating=risk
            ),
        )
        return {"reconciliations": _project_records(records)}
    try:
        records = AccountReconciliationService(_local_connection(connection)).list_reconciliations(
            status=status,
            owner=owner,
            period_name=period,
            entity_code=entity,
            risk_rating=risk,
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="accounts_list_failed", message=str(exc)) from exc
    return {"reconciliations": _project_records(records)}


@router.post("/reconciliations")
def create_reconciliation(
    request: Request,
    payload: CreateReconciliationRequest,
    current_user: AccountPrepare,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Create or update one account reconciliation record."""

    if server_accounts_enabled(request):
        scope = _server_scope(request, permissions=frozenset({"accounts.prepare"}), amount=abs(payload.balance))
        values = payload.model_dump()
        values.update(workspace=scope.workspace_id, actor_label=current_user.id, preparer="")
        record = execute_postgres_accounts(
            request, lambda repository, _tenant: repository.create_reconciliation(**values)
        )
        return {"reconciliation": _project_record(record)}
    try:
        record = AccountReconciliationService(_local_connection(connection)).create_reconciliation(
            period_name=payload.period_name,
            entity_code=payload.entity_code,
            account_code=payload.account_code,
            account_name=payload.account_name,
            workspace=payload.workspace,
            balance=payload.balance,
            owner=payload.owner,
            preparer=payload.preparer,
            reviewer=payload.reviewer,
            risk_rating=payload.risk_rating,
            materiality_threshold=payload.materiality_threshold,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="account_create_failed", message=str(exc)) from exc
    return {"reconciliation": _project_record(record)}


@router.get("/reconciliations/{reconciliation_id}")
def get_reconciliation(
    reconciliation_id: str,
    request: Request,
    current_user: AccountRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Read one account reconciliation record."""

    if server_accounts_enabled(request):
        _server_scope(
            request,
            permissions=frozenset({"accounts.read", "accounts.prepare", "accounts.review", "accounts.complete"}),
        )
        record = execute_postgres_accounts(
            request, lambda repository, _tenant: repository.get_reconciliation(reconciliation_id)
        )
        return {"reconciliation": _project_record(record)}
    try:
        record = AccountReconciliationService(_local_connection(connection)).get_reconciliation(reconciliation_id)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=404, code="account_not_found", message=str(exc)) from exc
    return {"reconciliation": _project_record(record)}


@router.post("/reconciliations/{reconciliation_id}/prepare")
def prepare_reconciliation(
    reconciliation_id: str,
    request: Request,
    payload: ActionRequest,
    current_user: AccountPrepare,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Prepare one account reconciliation."""

    if server_accounts_enabled(request):
        scope = _server_scope(request, permissions=frozenset({"accounts.prepare"}))
        record = execute_postgres_accounts(
            request,
            lambda repository, _tenant: repository.prepare(
                reconciliation_id=reconciliation_id, workspace=scope.workspace_id, actor_label=current_user.id
            ),
        )
        return {"reconciliation": _project_record(record)}
    try:
        record = AccountReconciliationService(_local_connection(connection)).prepare(
            reconciliation_id=reconciliation_id, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="account_prepare_failed", message=str(exc)) from exc
    return {"reconciliation": _project_record(record)}


@router.post("/reconciliations/{reconciliation_id}/submit")
def submit_reconciliation(
    reconciliation_id: str,
    request: Request,
    payload: ActionRequest,
    current_user: AccountPrepare,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Submit one account reconciliation."""

    if server_accounts_enabled(request):
        _server_scope(request, permissions=frozenset({"accounts.prepare"}))
        record = execute_postgres_accounts(
            request, lambda repository, _tenant: repository.submit(reconciliation_id, actor_label=current_user.id)
        )
        return {"reconciliation": _project_record(record)}
    try:
        record = AccountReconciliationService(_local_connection(connection)).submit(
            reconciliation_id, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="account_submit_failed", message=str(exc)) from exc
    return {"reconciliation": _project_record(record)}


@router.post("/reconciliations/{reconciliation_id}/review")
def review_reconciliation(
    reconciliation_id: str,
    request: Request,
    payload: ActionRequest,
    current_user: AccountReview,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Review one account reconciliation."""

    if server_accounts_enabled(request):
        _server_scope(request, permissions=frozenset({"accounts.review"}))
        record = execute_postgres_accounts(
            request,
            lambda repository, _tenant: repository.review(
                reconciliation_id, reviewer=current_user.id, actor_label=current_user.id
            ),
        )
        return {"reconciliation": _project_record(record)}
    try:
        record = AccountReconciliationService(_local_connection(connection)).review(
            reconciliation_id,
            reviewer=payload.reviewer,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="account_review_failed", message=str(exc)) from exc
    return {"reconciliation": _project_record(record)}


@router.post("/reconciliations/{reconciliation_id}/complete")
def complete_reconciliation(
    reconciliation_id: str,
    request: Request,
    payload: ActionRequest,
    current_user: AccountComplete,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Complete one account reconciliation."""

    if server_accounts_enabled(request):
        _server_scope(request, permissions=frozenset({"accounts.complete"}))
        record = execute_postgres_accounts(
            request, lambda repository, _tenant: repository.complete(reconciliation_id, actor_label=current_user.id)
        )
        return {"reconciliation": _project_record(record)}
    try:
        record = AccountReconciliationService(_local_connection(connection)).complete(
            reconciliation_id, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="account_complete_failed", message=str(exc)) from exc
    return {"reconciliation": _project_record(record)}
