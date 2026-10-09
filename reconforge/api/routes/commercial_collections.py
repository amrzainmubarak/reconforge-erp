"""Strict scoped preparation/review/posting of real native AR installments."""

from collections.abc import Callable
from typing import Annotated, Any, Literal

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
from reconforge.domain.commercial_collections import CommercialCollectionPreparation
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.infrastructure.postgres_commercial_collections import PostgresCommercialCollectionsRepository
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/commercial-collections", tags=["commercial-collections"])
Read = Annotated[LocalUser, Depends(required(frozenset({"finance_core.read", "receivables.read"})))]
Manage = Annotated[LocalUser, Depends(required(frozenset({"finance_core.manage", "sales.manage", "receivables.manage"})))]
Review = Annotated[LocalUser, Depends(required(frozenset({"finance_core.validate", "sales.approve", "receivables.manage"})))]
Post = Annotated[LocalUser, Depends(required(frozenset({"finance_core.post", "sales.manage", "receivables.manage"})))]


class PreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    source_kind: Literal["ARReceipt"] = "ARReceipt"
    source_id: str = Field(min_length=1, max_length=160)
    amount_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    journal_code: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    debit_account_code: str = Field(min_length=1, max_length=64)
    credit_account_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=500)
    receipt_number: str = Field(min_length=1, max_length=64)


class PhaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    expected_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


def project(plan: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "workspace_id", "organization_id", "legal_entity_id", "source_id", "source_kind", "entry_id",
            "period_id", "posting_date", "receipt_number", "currency_code", "currency_precision", "status", "phase", "plan_digest",
            "validation_digest", "preparer_actor_id", "reviewer_actor_id", "posting_effect_id", "receipt_id")
    return {**{key: plan[key] for key in keys}, "amount_minor": str(plan["amount_minor"]),
            "allocated_before_minor": str(plan["allocated_before_minor"]), "invoice_version": plan["invoice_version"]}


def execute(request: Request, user: LocalUser,
            operation: Callable[[PostgresCommercialCollectionsRepository, PostingActor, FinanceCoreExecutionScope], Any]) -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="installment_backend_unavailable", message="Collections require PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        try:
            return operation(PostgresCommercialCollectionsRepository(finance.connection, scope.tenant_id), actor, scope)
        except FinancePostingError as exc:
            status = (403 if "denied" in exc.code else 404 if "not_found" in exc.code
                      else 409 if any(word in exc.code for word in ("conflict", "changed", "review_invalid")) else 400)
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="installment_state_conflict", message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.post("/plans")
def prepare(request: Request, payload: PreparationRequest, user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.manage")
    def run(repository: PostgresCommercialCollectionsRepository, actor: PostingActor, bound: FinanceCoreExecutionScope) -> Any:
        arguments = payload.model_dump(exclude={"command_id", "amount_minor"})
        value = repository.prepare(CommercialCollectionPreparation(
            **arguments, amount_minor=int(payload.amount_minor), workspace_id=bound.workspace_id,
            organization_id=str(bound.organization_id), legal_entity_id=str(bound.legal_entity_id),
            organization_code=bound.organization_code, entity_code=bound.entity_code),
            command_id=payload.command_id, actor=actor)
        _authority(request, "finance_core.manage", value, source=True, audit=False)
        return {"plan": project(value)}

    return execute(request, user, run)


@router.get("/plans/{plan_id}")
def get(request: Request, plan_id: str, user: Read) -> dict[str, Any]:
    _authority(request, "finance_core.read")

    def run(repository: PostgresCommercialCollectionsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Any:
        value = repository.get(plan_id, actor=actor)
        _authority(request, "finance_core.read", value)
        return {"plan": project(value)}

    return execute(request, user, run)


@router.post("/plans/{plan_id}/review")
def review(request: Request, plan_id: str, payload: PhaseRequest, user: Review) -> dict[str, Any]:
    _authority(request, "finance_core.validate")

    def run(repository: PostgresCommercialCollectionsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Any:
        value = repository.get(plan_id, actor=actor)
        _authority(request, "finance_core.validate", value, source=True)
        return {"plan": project(repository.review(plan_id, **payload.model_dump(), actor=actor))}

    return execute(request, user, run)


@router.post("/plans/{plan_id}/post")
def post(request: Request, plan_id: str, payload: PhaseRequest, user: Post) -> dict[str, Any]:
    _authority(request, "finance_core.post")

    def run(repository: PostgresCommercialCollectionsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Any:
        value = repository.get(plan_id, actor=actor)
        _authority(request, "finance_core.post", value, source=True)
        return {"plan": project(repository.post(plan_id, **payload.model_dump(), actor=actor))}

    return execute(request, user, run)
