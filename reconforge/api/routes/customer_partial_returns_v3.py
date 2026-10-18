"""Fixed monetary Stock return protocol; no old-source upgrade or policy input."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from pydantic import Field, field_validator

from reconforge.api.errors import APIError
from reconforge.api.monetary_partial_return_contract import project_monetary_partial_response
from reconforge.api.monetary_public_contract import MAX_MINOR, MonetaryResponseError
from reconforge.api.routes import customer_partial_returns as legacy
from reconforge.api.routes.operational_fx_tax import RateRequest
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.api.server_identity import request_execution_scope
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.monetary_customer_partial_return_commands import (
    MonetaryPartialRefundPreparation,
    MonetaryPartialReturnPreparation,
    MonetaryPartialReversePreparation,
)
from reconforge.domain.operational_fx_tax import HistoricalRate
from reconforge.infrastructure.postgres_monetary_customer_partial_returns import (
    PostgresMonetaryCustomerPartialReturnsRepository,
)
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/customer-partial-returns", tags=["customer-partial-returns-monetary"])


class ReturnRequest(legacy.HistoryRequest):
    source_order_id: str = Field(min_length=1, max_length=160)
    quantity_scaled: str = Field(pattern=r"^[1-9][0-9]{0,18}$")

    @field_validator("quantity_scaled")
    @classmethod
    def bounded_quantity(cls, value: str) -> str:
        if int(value) > MAX_MINOR:
            raise ValueError("The quantity exceeds the bounded native contract.")
        return value


class RefundRequest(legacy.RefundRequest):
    settlement_rate: RateRequest | None


def execute(request: Request, user: LocalUser,
            action: Callable[[PostgresMonetaryCustomerPartialReturnsRepository, PostingActor, FinanceCoreExecutionScope], Any]) -> dict[str, Any]:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="monetary_partial_return_backend_unavailable", message="Monetary partial returns require PostgreSQL.")
    actor = legacy._actor(request, user)
    request_execution_scope(request, permission="finance_core.read")

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        if not scope.organization_id or not scope.legal_entity_id or not scope.organization_code or not scope.entity_code:
            raise APIError(status_code=403, code="monetary_partial_return_scope_denied", message="Select an organization and legal entity.")
        try:
            owner = PostgresMonetaryCustomerPartialReturnsRepository(finance.connection, scope.tenant_id)
            return project_monetary_partial_response(action(owner, actor, scope), {
                "workspace_id": scope.workspace_id, "organization_id": scope.organization_id, "legal_entity_id": scope.legal_entity_id,
            })
        except MonetaryResponseError as exc:
            raise APIError(status_code=503, code="monetary_partial_return_response_invalid", message="The native monetary acknowledgement could not be verified.") from exc
        except FinancePostingError as exc:
            denied = any(word in exc.code for word in ("denied", "permission", "human", "step_up"))
            raise APIError(status_code=403 if denied else 404 if "not_found" in exc.code else 409, code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="monetary_partial_return_state_conflict", message="The native source state refused this command.") from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.get("/plans")
def list_plans(request: Request, user: legacy.Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: owner.list_plans({
        "workspace_id": scope.workspace_id, "organization_id": scope.organization_id, "legal_entity_id": scope.legal_entity_id,
    }, actor=actor))


@router.get("/plans/{plan_id}")
def get_plan(request: Request, plan_id: str, user: legacy.Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.get(plan_id, actor=actor)})


@router.get("/sources/{source_order_id}/balance")
def balance(request: Request, source_order_id: str, user: legacy.Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"balance": owner.balance(source_order_id, {
        "workspace_id": scope.workspace_id, "organization_id": scope.organization_id, "legal_entity_id": scope.legal_entity_id,
    }, actor=actor)})


@router.post("/plans")
def prepare(request: Request, body: ReturnRequest, user: legacy.Manage) -> dict[str, Any]:
    def action(owner: PostgresMonetaryCustomerPartialReturnsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        fields = body.model_dump(exclude={"command_id", "quantity_scaled"})
        command = MonetaryPartialReturnPreparation(**fields, quantity_scaled=int(body.quantity_scaled), workspace_id=scope.workspace_id,
            organization_id=str(scope.organization_id), legal_entity_id=str(scope.legal_entity_id),
            organization_code=scope.organization_code, entity_code=scope.entity_code)
        return {"plan": owner.prepare(command, command_id=body.command_id, actor=actor)}
    return execute(request, user, action)


@router.post("/plans/{return_id}/refunds")
def prepare_refund(request: Request, return_id: str, body: RefundRequest, user: legacy.Manage) -> dict[str, Any]:
    def action(owner: PostgresMonetaryCustomerPartialReturnsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        fields = body.model_dump(exclude={"command_id", "amount_minor", "settlement_rate"})
        command = MonetaryPartialRefundPreparation(return_id=return_id, **fields, amount_minor=int(body.amount_minor),
            settlement_rate=HistoricalRate(**body.settlement_rate.model_dump()) if body.settlement_rate is not None else None)
        return {"plan": owner.prepare_refund(command, command_id=body.command_id, actor=actor)}
    return execute(request, user, action)


@router.post("/plans/{original_id}/reversals")
def prepare_reversal(request: Request, original_id: str, body: legacy.ReversalRequest, user: legacy.Manage) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.prepare_reversal(
        MonetaryPartialReversePreparation(original_id=original_id, **body.model_dump(exclude={"command_id"})),
        command_id=body.command_id, actor=actor)})


@router.post("/plans/{plan_id}/review")
def review(request: Request, plan_id: str, body: legacy.PhaseRequest, user: legacy.Review) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.review(plan_id, **body.model_dump(), actor=actor)})


@router.post("/plans/{plan_id}/post")
def post(request: Request, plan_id: str, body: legacy.PhaseRequest, user: legacy.Post) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.post(plan_id, **body.model_dump(), actor=actor)})


@router.post("/plans/{plan_id}/cancel")
def cancel(request: Request, plan_id: str, body: legacy.PhaseRequest, user: legacy.Cancel) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"plan": owner.cancel(plan_id, **body.model_dump(), actor=actor)})
