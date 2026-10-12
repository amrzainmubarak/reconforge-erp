"""Current-authority appropriation-backed native purchase and AP commands."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.errors import APIError
from reconforge.api.routes.procurement_operations import execute, required
from reconforge.api.routes.procurement_partial import MultilineOrderRequest
from reconforge.api.server_finance_core import FinanceCoreExecutionScope
from reconforge.api.server_identity import request_execution_scope
from reconforge.auth.models import LocalUser
from reconforge.domain.budget_control import BudgetControlError
from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.procurement_commitments import BudgetPurchasePreparation
from reconforge.domain.procurement_operations import READ
from reconforge.domain.procurement_partial import MultilineProcurementPreparation, ProcurementOrderLine
from reconforge.infrastructure.postgres_procurement_commitments import PostgresProcurementCommitmentRepository
from reconforge.infrastructure.postgres_procurement_operations import (
    PERMISSIONS,
    PostgresProcurementOperationsRepository,
)

router = APIRouter(prefix="/procurement-commitments", tags=["procurement-commitments"])
BUDGET_READ = READ | frozenset({"budget_control.read"})
CREATE = BUDGET_READ | PERMISSIONS["create"] | frozenset({"budget_control.manage"})
CONSUME = BUDGET_READ | PERMISSIONS["post-accrual"] | frozenset({"budget_control.manage"})
RELEASE = BUDGET_READ | PERMISSIONS["approve-order"] | frozenset({"budget_control.manage"})


class BudgetOrderRequest(MultilineOrderRequest):
    budget_id: str = Field(min_length=1, max_length=160)
    expected_budget_version: int = Field(ge=1, le=9_000_000_000_000_000_000)
    reason: str = Field(min_length=1, max_length=500)
    command_id: str = Field(min_length=1, max_length=140)


class CommitmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    expected_order_version: int = Field(ge=1, le=9_000_000_000_000_000_000)
    expected_budget_version: int = Field(ge=1, le=9_000_000_000_000_000_000)
    reason: str = Field(min_length=1, max_length=500)


class ConsumeRequest(CommitmentRequest):
    invoice_id: str = Field(min_length=1, max_length=160)


class ReleaseRequest(CommitmentRequest):
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


def _execute(request: Request, user: LocalUser, permissions: frozenset[str],
             operation: Callable[[PostgresProcurementCommitmentRepository, PostingActor, FinanceCoreExecutionScope], Any],
             *, organization_code: str = "", entity_code: str = "") -> Any:
    def invoke(shared: PostgresProcurementOperationsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Any:
        try:
            return operation(PostgresProcurementCommitmentRepository(shared.connection, scope.tenant_id,
                require_live_session_assurance=True), actor, scope)
        except BudgetControlError as exc:
            denied = any(word in str(exc).lower() for word in ("authority", "permission", "identity", "authentication", "session", "assurance"))
            raise APIError(status_code=403 if denied else 409,
                code="procurement_commitment_denied" if denied else "procurement_commitment_conflict", message=str(exc)) from exc
    return execute(request, user, permissions, invoke, organization_code=organization_code, entity_code=entity_code)


@router.post("/orders")
def create(request: Request, payload: BudgetOrderRequest,
           user: LocalUser = Depends(required(CREATE))) -> dict[str, Any]:
    selected = request_execution_scope(request)
    if payload.workspace not in {"default", selected.workspace_id}:
        raise APIError(status_code=403, code="workspace_scope_denied", message="Workspace is outside current authority.")
    def run(repository: PostgresProcurementCommitmentRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        header = payload.model_dump(exclude={"command_id", "lines", "workspace", "organization_code", "entity_code",
                                            "budget_id", "expected_budget_version", "reason"})
        order = MultilineProcurementPreparation(**header, workspace=scope.workspace_id,
            organization_code=scope.organization_code, entity_code=scope.entity_code,
            lines=tuple(ProcurementOrderLine(**{**line.model_dump(), "unit_price_minor": int(line.unit_price_minor)}) for line in payload.lines))
        return repository.create(BudgetPurchasePreparation(budget_id=payload.budget_id,
            expected_budget_version=payload.expected_budget_version, order=order, reason=payload.reason), command_id=payload.command_id, actor=actor)
    return _execute(request, user, CREATE, run, organization_code=payload.organization_code, entity_code=payload.entity_code)


@router.get("/orders/{order_id}")
def get(request: Request, order_id: str, user: LocalUser = Depends(required(BUDGET_READ))) -> dict[str, Any]:
    return _execute(request, user, BUDGET_READ, lambda repository, actor, scope: repository.get(order_id, actor=actor))


@router.post("/orders/{order_id}/consume")
def consume(request: Request, order_id: str, payload: ConsumeRequest,
            user: LocalUser = Depends(required(CONSUME))) -> dict[str, Any]:
    fields = payload.model_dump()
    invoice_id = fields.pop("invoice_id")
    return _execute(request, user, CONSUME, lambda repository, actor, scope:
        repository.consume_invoice(order_id, invoice_id, **fields, actor=actor))


@router.post("/orders/{order_id}/release")
def release(request: Request, order_id: str, payload: ReleaseRequest,
            user: LocalUser = Depends(required(RELEASE))) -> dict[str, Any]:
    return _execute(request, user, RELEASE, lambda repository, actor, scope:
        repository.release(order_id, **payload.model_dump(), actor=actor))
