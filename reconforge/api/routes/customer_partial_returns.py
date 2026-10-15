"""Governed persisted partial stock credits, refunds and explicit reversals."""

from collections.abc import Callable
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from reconforge.api.customer_partial_return_contract import (
    CustomerPartialReturnResponseError,
    project_partial_response,
    project_partial_response_v2,
)
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
from reconforge.domain.customer_partial_return_commands import (
    CustomerPartialRefundPreparation,
    CustomerPartialReturnPreparation,
    CustomerPartialReversePreparation,
)
from reconforge.domain.customer_returns import MAX_MINOR
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.infrastructure.postgres_customer_partial_returns import (
    PERMISSIONS,
    READ,
    PostgresCustomerPartialReturnsRepository,
)
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/customer-partial-returns", tags=["customer-partial-returns"])
Read = Annotated[LocalUser, Depends(required(READ))]
Manage = Annotated[LocalUser, Depends(required(PERMISSIONS["prepare"]))]
Review = Annotated[LocalUser, Depends(required(PERMISSIONS["review"]))]
Post = Annotated[LocalUser, Depends(required(PERMISSIONS["post"]))]
Cancel = Annotated[LocalUser, Depends(required(PERMISSIONS["cancel"]))]


class HistoryRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    command_id: str = Field(min_length=1, max_length=140)
    expected_history_version: int = Field(ge=0, le=255)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("posting_date")
    @classmethod
    def calendar_date(cls, value: str) -> str:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("An exact valid ISO business date is required.")
        return value


class ReturnRequest(HistoryRequest):
    source_order_id: str = Field(min_length=1, max_length=160)
    quantity_scaled: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    journal_code: str = Field(min_length=1, max_length=64)
    refund_liability_account_code: str = Field(min_length=1, max_length=64)
    cash_account_code: str = Field(min_length=1, max_length=64)

    @field_validator("quantity_scaled")
    @classmethod
    def bounded_quantity(cls, value: str) -> str:
        if int(value) > MAX_MINOR:
            raise ValueError("Quantity exceeds the exact bounded native contract.")
        return value


class RefundRequest(HistoryRequest):
    amount_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")

    @field_validator("amount_minor")
    @classmethod
    def bounded_amount(cls, value: str) -> str:
        if int(value) > MAX_MINOR:
            raise ValueError("Amount exceeds the exact bounded native contract.")
        return value


class ReversalRequest(HistoryRequest):
    """Prepare a new reviewed inverse; this request never posts immediately."""


class PhaseRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    command_id: str = Field(min_length=1, max_length=140)
    expected_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


def execute(request: Request, user: LocalUser,
            action: Callable[[PostgresCustomerPartialReturnsRepository, PostingActor, FinanceCoreExecutionScope], Any]) -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="customer_partial_return_backend_unavailable",
                       message="Persisted partial stock credits require PostgreSQL.")
    actor = _actor(request, user)
    protocol = getattr(request.state, "customer_partial_return_protocol_version", 1)
    if type(protocol) is not int or protocol not in (1, 2):
        raise APIError(status_code=503, code="customer_partial_return_protocol_invalid",
                       message="The server partial-return protocol is unavailable.")

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        try:
            owner = (PostgresCustomerPartialReturnsRepository(finance.connection, scope.tenant_id, protocol_version=2)
                     if protocol == 2 else PostgresCustomerPartialReturnsRepository(finance.connection, scope.tenant_id))
            projector = project_partial_response_v2 if protocol == 2 else project_partial_response
            return projector(action(owner, actor, scope), {
                "workspace_id": scope.workspace_id, "organization_id": scope.organization_id,
                "legal_entity_id": scope.legal_entity_id,
            })
        except CustomerPartialReturnResponseError as exc:
            raise APIError(status_code=503, code="customer_partial_return_response_invalid",
                           message="The native partial-return acknowledgement could not be verified.") from exc
        except FinancePostingError as exc:
            status = 403 if "denied" in exc.code or exc.code in {"posting_human_required", "posting_step_up_required"} else 404 if "not_found" in exc.code else 409
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="customer_partial_return_state_conflict",
                           message="The native partial-return state refused this command.") from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.get("/plans")
def list_plans(request: Request, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: owner.list_plans({
        "workspace_id": scope.workspace_id, "organization_id": scope.organization_id,
        "legal_entity_id": scope.legal_entity_id,
    }, actor=actor))


@router.get("/plans/{plan_id}")
def get(request: Request, plan_id: str, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.get(plan_id, actor=actor)})


@router.get("/sources/{source_order_id}/balance")
def balance(request: Request, source_order_id: str, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"balance": owner.balance(source_order_id, {
        "workspace_id": scope.workspace_id, "organization_id": scope.organization_id,
        "legal_entity_id": scope.legal_entity_id,
    }, actor=actor)})


@router.post("/plans")
def prepare(request: Request, payload: ReturnRequest, user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.manage")

    def run(owner: PostgresCustomerPartialReturnsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Any:
        args = payload.model_dump(exclude={"command_id", "quantity_scaled"})
        preparation = CustomerPartialReturnPreparation(
            **args, quantity_scaled=int(payload.quantity_scaled), workspace_id=scope.workspace_id,
            organization_id=str(scope.organization_id), legal_entity_id=str(scope.legal_entity_id),
            organization_code=scope.organization_code, entity_code=scope.entity_code,
        )
        return {"plan": owner.prepare(preparation, command_id=payload.command_id, actor=actor)}

    return execute(request, user, run)


@router.post("/plans/{return_id}/refunds")
def prepare_refund(request: Request, return_id: str, payload: RefundRequest, user: Manage) -> dict[str, Any]:
    args = payload.model_dump(exclude={"command_id", "amount_minor"})
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.prepare_refund(
        CustomerPartialRefundPreparation(**args, return_id=return_id, amount_minor=int(payload.amount_minor)),
        command_id=payload.command_id, actor=actor,
    )})


@router.post("/plans/{original_id}/reversals")
def prepare_reversal(request: Request, original_id: str, payload: ReversalRequest, user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.reverse")
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.prepare_reversal(
        CustomerPartialReversePreparation(**payload.model_dump(exclude={"command_id"}), original_id=original_id),
        command_id=payload.command_id, actor=actor,
    )})


@router.post("/plans/{plan_id}/review")
def review(request: Request, plan_id: str, payload: PhaseRequest, user: Review) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.review(plan_id, **payload.model_dump(), actor=actor)})


@router.post("/plans/{plan_id}/post")
def post(request: Request, plan_id: str, payload: PhaseRequest, user: Post) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.post(plan_id, **payload.model_dump(), actor=actor)})


@router.post("/plans/{plan_id}/cancel")
def cancel(request: Request, plan_id: str, payload: PhaseRequest, user: Cancel) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.cancel(plan_id, **payload.model_dump(), actor=actor)})
