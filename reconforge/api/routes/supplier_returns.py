"""Current-human original receipt return and exact native supplier-debit API."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.errors import APIError
from reconforge.api.routes.procurement_operations import execute, required
from reconforge.auth.models import LocalUser
from reconforge.domain.budget_control import BudgetControlError
from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.supplier_returns import SupplierReturnPreparation
from reconforge.infrastructure.postgres_procurement_operations import PostgresProcurementOperationsRepository
from reconforge.infrastructure.postgres_supplier_returns import PERMISSIONS, READ, PostgresSupplierReturnsRepository

router = APIRouter(prefix="/supplier-returns", tags=["supplier-returns"])


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    order_id: str = Field(min_length=1, max_length=140)
    receipt_id: str = Field(min_length=1, max_length=140)
    invoice_id: str = Field(min_length=1, max_length=140)
    number: str = Field(min_length=5, max_length=64, pattern=r"^SR1-")
    period_id: str = Field(min_length=1, max_length=140)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    expense_account_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=500)
    command_id: str = Field(min_length=1, max_length=140)


class PhaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=500)
    command_id: str = Field(min_length=1, max_length=140)


def _execute(request: Request, user: LocalUser, permissions: frozenset[str],
             operation: Callable[[PostgresSupplierReturnsRepository, PostingActor], Any]) -> Any:
    def invoke(shared: PostgresProcurementOperationsRepository, actor: PostingActor, scope: Any) -> Any:
        try:
            return operation(PostgresSupplierReturnsRepository(shared.connection, scope.tenant_id,
                require_live_session_assurance=True), actor)
        except BudgetControlError as exc:
            raise APIError(status_code=403, code="supplier_return_authority_denied", message=str(exc)) from exc
    return execute(request, user, permissions, invoke)


@router.post("/plans")
def prepare(request: Request, payload: PrepareRequest, user: LocalUser = Depends(required(PERMISSIONS["prepare"]))) -> dict[str, Any]:
    return _execute(request, user, PERMISSIONS["prepare"], lambda repository, actor:
        repository.prepare(SupplierReturnPreparation(**payload.model_dump(exclude={"command_id"})), command_id=payload.command_id, actor=actor))


@router.get("/plans/{plan_id}")
def get(request: Request, plan_id: str, user: LocalUser = Depends(required(READ))) -> dict[str, Any]:
    return _execute(request, user, READ, lambda repository, actor: repository.get(plan_id, actor=actor))


@router.get("/orders/{order_id}")
def page(request: Request, order_id: str, user: LocalUser = Depends(required(READ))) -> dict[str, Any]:
    return _execute(request, user, READ, lambda repository, actor: repository.list_plans(order_id, actor=actor))


@router.post("/plans/{plan_id}/review")
def review(request: Request, plan_id: str, payload: PhaseRequest, user: LocalUser = Depends(required(PERMISSIONS["review"]))) -> dict[str, Any]:
    return _execute(request, user, PERMISSIONS["review"], lambda repository, actor: repository.review(plan_id, **payload.model_dump(), actor=actor))


@router.post("/plans/{plan_id}/post")
def post(request: Request, plan_id: str, payload: PhaseRequest, user: LocalUser = Depends(required(PERMISSIONS["post"]))) -> dict[str, Any]:
    return _execute(request, user, PERMISSIONS["post"], lambda repository, actor: repository.post(plan_id, **payload.model_dump(), actor=actor))


@router.post("/plans/{plan_id}/cancel")
def cancel(request: Request, plan_id: str, payload: PhaseRequest, user: LocalUser = Depends(required(PERMISSIONS["cancel"]))) -> dict[str, Any]:
    return _execute(request, user, PERMISSIONS["cancel"], lambda repository, actor: repository.cancel(plan_id, **payload.model_dump(), actor=actor))
