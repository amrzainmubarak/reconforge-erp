"""Whole original stock-source credits and individually governed partial refunds."""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.operational_finance import _authority
from reconforge.api.routes.procurement_operations import required
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.auth.models import LocalUser
from reconforge.domain.customer_returns import CustomerRefundPreparation, CustomerReturnPreparation
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.infrastructure.postgres_customer_returns import PERMISSIONS, READ, PostgresCustomerReturnsRepository
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/customer-returns", tags=["customer-returns"])
Read = Annotated[LocalUser, Depends(required(READ))]
Manage = Annotated[LocalUser, Depends(required(PERMISSIONS["prepare"]))]
Review = Annotated[LocalUser, Depends(required(PERMISSIONS["review"]))]
Post = Annotated[LocalUser, Depends(required(PERMISSIONS["post"]))]
Cancel = Annotated[LocalUser, Depends(required(PERMISSIONS["cancel"]))]


class ReturnRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    command_id: str = Field(min_length=1, max_length=140)
    source_order_id: str = Field(min_length=1, max_length=160)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    journal_code: str = Field(min_length=1, max_length=64)
    refund_liability_account_code: str = Field(min_length=1, max_length=64)
    cash_account_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=500)


class RefundRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    command_id: str = Field(min_length=1, max_length=140)
    amount_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(min_length=1, max_length=500)


class PhaseRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    command_id: str = Field(min_length=1, max_length=140)
    expected_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


def project(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {name: project(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [project(item) for item in value]
    return str(value) if type(value) is int and (key.endswith("_minor") or key.endswith("_scaled")) else value


def execute(request: Request, user: LocalUser,
            action: Callable[[PostgresCustomerReturnsRepository, PostingActor, FinanceCoreExecutionScope], Any]) -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="customer_return_backend_unavailable", message="Original stock credits require PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        try:
            return project(action(PostgresCustomerReturnsRepository(finance.connection, scope.tenant_id), actor, scope))
        except FinancePostingError as exc:
            status = 403 if "denied" in exc.code else 404 if "not_found" in exc.code else 409
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="customer_return_state_conflict", message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.post("/plans")
def prepare(request: Request, payload: ReturnRequest, user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.manage")

    def run(owner: PostgresCustomerReturnsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Any:
        args = payload.model_dump(exclude={"command_id"})
        plan = owner.prepare(CustomerReturnPreparation(**args, workspace_id=scope.workspace_id, organization_id=str(scope.organization_id),
            legal_entity_id=str(scope.legal_entity_id), organization_code=scope.organization_code, entity_code=scope.entity_code),
            command_id=payload.command_id, actor=actor)
        return {"plan": plan}

    return execute(request, user, run)


@router.get("/plans")
def list_plans(request: Request, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: owner.list_plans({"workspace_id": scope.workspace_id,
        "organization_id": scope.organization_id, "legal_entity_id": scope.legal_entity_id}, actor=actor))


@router.get("/plans/{plan_id}")
def get(request: Request, plan_id: str, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.get(plan_id, actor=actor)})


@router.get("/plans/{plan_id}/balance")
def balance(request: Request, plan_id: str, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"balance": owner.balance(plan_id, actor=actor)})


@router.post("/plans/{return_id}/refunds")
def prepare_refund(request: Request, return_id: str, payload: RefundRequest, user: Manage) -> dict[str, Any]:
    args = payload.model_dump(exclude={"command_id", "amount_minor"})
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.prepare_refund(CustomerRefundPreparation(
        **args, return_id=return_id, amount_minor=int(payload.amount_minor)), command_id=payload.command_id, actor=actor)})


@router.post("/plans/{plan_id}/review")
def review(request: Request, plan_id: str, payload: PhaseRequest, user: Review) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.review(plan_id, **payload.model_dump(), actor=actor)})


@router.post("/plans/{plan_id}/post")
def post(request: Request, plan_id: str, payload: PhaseRequest, user: Post) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.post(plan_id, **payload.model_dump(), actor=actor)})


@router.post("/plans/{plan_id}/cancel")
def cancel(request: Request, plan_id: str, payload: PhaseRequest, user: Cancel) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.cancel(plan_id, **payload.model_dump(), actor=actor)})
