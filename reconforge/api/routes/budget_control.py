"""Authenticated real operational budget commands and exact textual money reads."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from reconforge.api.dependencies import get_local_db, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_budget_control import execute_postgres_budget_control, server_budget_control_enabled
from reconforge.api.server_identity import server_identity_enabled
from reconforge.auth import AuthRepositoryError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.domain.budget_control import BudgetControlError, BudgetDefinition, BudgetScope, CommitmentAction, minor
from reconforge.infrastructure.budget_control_repository import BudgetControlRepositoryBase
from reconforge.infrastructure.sqlite_budget_control import SQLiteBudgetControlRepository
from reconforge.platform.common import PlatformError, ServerPrincipal, server_principal_context

router = APIRouter(prefix="/budget-control", tags=["budget-control"])
BudgetRead = Annotated[LocalUser, Depends(require_permission("budget_control.read"))]
BudgetManage = Annotated[LocalUser, Depends(require_permission("budget_control.manage"))]
BudgetApprove = Annotated[LocalUser, Depends(require_permission("budget_control.approve"))]
T = TypeVar("T")


class ScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str = Field(min_length=1, max_length=160)
    organization_id: str = Field(min_length=1, max_length=160)
    legal_entity_id: str = Field(min_length=1, max_length=160)

    def scope(self) -> BudgetScope:
        return BudgetScope(self.workspace_id, self.organization_id, self.legal_entity_id)


class BudgetRequest(ScopeRequest):
    budget_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    period_id: str = Field(min_length=1, max_length=160)
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    limit_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    command_id: str = Field(min_length=1, max_length=200)


class ReviewRequest(ScopeRequest):
    expected_version: StrictInt = Field(ge=1, le=9_000_000_000_000_000_000)
    reason: str = Field(min_length=1, max_length=500)
    command_id: str = Field(min_length=1, max_length=200)


class CommitmentRequest(ReviewRequest):
    operation: str = Field(pattern=r"^(Reserve|Release|Consume)$")
    amount_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    operation_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_reference: str = Field(min_length=1, max_length=160)


def _local_principal(connection: sqlite3.Connection, current_user: LocalUser) -> ServerPrincipal:
    """Bind a fresh local human identity for the same request transaction.

    The local bearer session was created by password authentication.  SQLite
    has no privileged-session table, so this adapter treats that verified local
    session as the current human assurance while the repository independently
    re-reads the enabled identity and active RBAC assignments inside its own
    BEGIN IMMEDIATE transaction.  It intentionally grants only the requested
    canonical scope; local per-scope grants are not implemented by the shared
    SQLite identity schema.
    """

    try:
        service = LocalAuthService(connection)
        user = service.users.get_by_id(current_user.id)
        if user is None or user.disabled or user.username != current_user.username:
            raise BudgetControlError("Budget actor has no active persisted identity.")
        return ServerPrincipal(
            user=user,
            permissions=frozenset(service.roles.user_permissions(user.username)),
            step_up_active=True,
        )
    except AuthRepositoryError as exc:
        raise BudgetControlError("Budget actor has no active persisted identity.") from exc


def _call(request: Request, connection: sqlite3.Connection | None, current_user: LocalUser, scope: BudgetScope,
        operation: Callable[[BudgetControlRepositoryBase], T]) -> T:
    try:
        if server_budget_control_enabled(request):
            return execute_postgres_budget_control(request, scope, operation)
        if server_identity_enabled(request) or connection is None:
            raise APIError(status_code=503, code="budget_control_unavailable", message="Budget backend is unavailable.")
        with server_principal_context(_local_principal(connection, current_user)):
            return operation(SQLiteBudgetControlRepository(connection))
    except (BudgetControlError, PlatformError) as exc:
        message = str(exc)
        denied = any(word in message.lower() for word in ("authority", "permission", "identity", "authentication"))
        raise APIError(status_code=403 if denied else 409, code="budget_control_denied" if denied else "budget_control_conflict", message=message) from exc


@router.get("/envelopes")
def list_envelopes(request: Request, current_user: BudgetRead,
        workspace_id: str = Query(min_length=1, max_length=160), organization_id: str = Query(min_length=1, max_length=160),
        legal_entity_id: str = Query(min_length=1, max_length=160), limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10_000_000), connection: sqlite3.Connection | None = Depends(get_local_db)) -> dict[str, Any]:
    scope = BudgetScope(workspace_id, organization_id, legal_entity_id)
    return _call(request, connection, current_user, scope, lambda repository: repository.list(scope, limit=limit, offset=offset))


@router.get("/envelopes/{budget_id}")
def get_envelope(request: Request, budget_id: str, current_user: BudgetRead,
        workspace_id: str = Query(min_length=1, max_length=160), organization_id: str = Query(min_length=1, max_length=160),
        legal_entity_id: str = Query(min_length=1, max_length=160), connection: sqlite3.Connection | None = Depends(get_local_db)) -> dict[str, Any]:
    scope = BudgetScope(workspace_id, organization_id, legal_entity_id)
    return _call(request, connection, current_user, scope, lambda repository: repository.get(scope, budget_id))


@router.post("/envelopes")
def create_envelope(request: Request, payload: BudgetRequest, current_user: BudgetManage,
        connection: sqlite3.Connection | None = Depends(get_local_db)) -> dict[str, Any]:
    scope = payload.scope()
    definition = BudgetDefinition(payload.budget_code, payload.name, payload.period_id, payload.currency_code, minor(payload.limit_minor))
    return _call(request, connection, current_user, scope, lambda repository: repository.create(scope, definition, command_id=payload.command_id))


@router.post("/envelopes/{budget_id}/submit")
def submit_envelope(request: Request, budget_id: str, payload: ReviewRequest, current_user: BudgetManage,
        connection: sqlite3.Connection | None = Depends(get_local_db)) -> dict[str, Any]:
    scope = payload.scope()
    return _call(request, connection, current_user, scope, lambda repository: repository.transition(scope, budget_id, action="submit", expected_version=payload.expected_version, reason=payload.reason, command_id=payload.command_id))


@router.post("/envelopes/{budget_id}/approve")
def approve_envelope(request: Request, budget_id: str, payload: ReviewRequest, current_user: BudgetApprove,
        connection: sqlite3.Connection | None = Depends(get_local_db)) -> dict[str, Any]:
    scope = payload.scope()
    return _call(request, connection, current_user, scope, lambda repository: repository.transition(scope, budget_id, action="approve", expected_version=payload.expected_version, reason=payload.reason, command_id=payload.command_id))


@router.post("/envelopes/{budget_id}/commitments")
def reserve(request: Request, budget_id: str, payload: CommitmentRequest, current_user: BudgetManage,
        connection: sqlite3.Connection | None = Depends(get_local_db)) -> dict[str, Any]:
    scope = payload.scope()
    if payload.operation != "Reserve":
        raise APIError(status_code=422, code="budget_operation_invalid", message="New commitments require Reserve.")
    action = CommitmentAction(payload.operation, minor(payload.amount_minor), payload.operation_date, payload.source_reference, payload.reason)
    return _call(request, connection, current_user, scope, lambda repository: repository.record(scope, budget_id, action, expected_version=payload.expected_version, command_id=payload.command_id))


@router.post("/envelopes/{budget_id}/commitments/{commitment_id}/events")
def settle(request: Request, budget_id: str, commitment_id: str, payload: CommitmentRequest, current_user: BudgetManage,
        connection: sqlite3.Connection | None = Depends(get_local_db)) -> dict[str, Any]:
    scope = payload.scope()
    if payload.operation == "Reserve":
        raise APIError(status_code=422, code="budget_operation_invalid", message="Existing commitments require Release or Consume.")
    action = CommitmentAction(payload.operation, minor(payload.amount_minor), payload.operation_date, payload.source_reference, payload.reason)
    return _call(request, connection, current_user, scope, lambda repository: repository.record(scope, budget_id, action, expected_version=payload.expected_version, command_id=payload.command_id, commitment_id=commitment_id))
