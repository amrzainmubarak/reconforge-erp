"""Account reconciliation routes for the local API."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import get_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
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


@router.get("/reconciliations")
def list_reconciliations(
    current_user: AccountRead,
    connection: sqlite3.Connection = Depends(get_db),
    status: str = "",
    owner: str = "",
    period: str = "",
    entity: str = "",
    risk: str = "",
) -> dict[str, object]:
    """List DB-backed account reconciliation records."""

    try:
        records = AccountReconciliationService(connection).list_reconciliations(
            status=status,
            owner=owner,
            period_name=period,
            entity_code=entity,
            risk_rating=risk,
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="accounts_list_failed", message=str(exc)) from exc
    return {"reconciliations": records}


@router.post("/reconciliations")
def create_reconciliation(
    payload: CreateReconciliationRequest,
    current_user: AccountPrepare,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Create or update one account reconciliation record."""

    try:
        record = AccountReconciliationService(connection).create_reconciliation(
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
    return {"reconciliation": record}


@router.get("/reconciliations/{reconciliation_id}")
def get_reconciliation(
    reconciliation_id: str,
    current_user: AccountRead,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Read one account reconciliation record."""

    try:
        record = AccountReconciliationService(connection).get_reconciliation(reconciliation_id)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=404, code="account_not_found", message=str(exc)) from exc
    return {"reconciliation": record}


@router.post("/reconciliations/{reconciliation_id}/prepare")
def prepare_reconciliation(
    reconciliation_id: str,
    payload: ActionRequest,
    current_user: AccountPrepare,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Prepare one account reconciliation."""

    try:
        record = AccountReconciliationService(connection).prepare(
            reconciliation_id=reconciliation_id, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="account_prepare_failed", message=str(exc)) from exc
    return {"reconciliation": record}


@router.post("/reconciliations/{reconciliation_id}/submit")
def submit_reconciliation(
    reconciliation_id: str,
    payload: ActionRequest,
    current_user: AccountPrepare,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Submit one account reconciliation."""

    try:
        record = AccountReconciliationService(connection).submit(reconciliation_id, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="account_submit_failed", message=str(exc)) from exc
    return {"reconciliation": record}


@router.post("/reconciliations/{reconciliation_id}/review")
def review_reconciliation(
    reconciliation_id: str,
    payload: ActionRequest,
    current_user: AccountReview,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Review one account reconciliation."""

    try:
        record = AccountReconciliationService(connection).review(
            reconciliation_id,
            reviewer=payload.reviewer,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="account_review_failed", message=str(exc)) from exc
    return {"reconciliation": record}


@router.post("/reconciliations/{reconciliation_id}/complete")
def complete_reconciliation(
    reconciliation_id: str,
    payload: ActionRequest,
    current_user: AccountComplete,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Complete one account reconciliation."""

    try:
        record = AccountReconciliationService(connection).complete(reconciliation_id, actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="account_complete_failed", message=str(exc)) from exc
    return {"reconciliation": record}
