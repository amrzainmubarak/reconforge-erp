"""FastAPI routes for CRM Opportunities, Quotations, and Customer Contracts."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.enterprise_scope import enterprise_transaction
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.auth.repositories import RoleRepository
from reconforge.domain.crm_contracts import (
    BillingFrequency,
    CustomerQuotation,
    Opportunity,
    OpportunityStage,
    QuotationLineItem,
    Subscription,
    SubscriptionPlan,
    calculate_plan_change_proration,
    cancel_subscription_with_refund,
    convert_quote_to_contract,
    renew_contract,
    resume_contract,
    suspend_contract,
)
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres_crm_contracts import (
    PostgresCRMContractsRepository,
)
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.sqlite_crm_contracts import (
    SqliteCRMContractsRepository,
)

router = APIRouter(prefix="/crm/contracts", tags=["crm-contracts"])
Read = Annotated[LocalUser, Depends(require_permission("sales.manage"))]
Manage = Annotated[LocalUser, Depends(require_permission("sales.manage"))]
Approve = Annotated[LocalUser, Depends(require_permission("sales.approve"))]


@contextmanager
def _repo(
    request: Request, *, permissions: frozenset[str], permission_mode: Literal["all", "any"] = "all"
) -> Iterator[tuple[SqliteCRMContractsRepository | PostgresCRMContractsRepository, str]]:
    with enterprise_transaction(request, permissions=permissions, permission_mode=permission_mode) as business:
        if business is not None:
            connection = business.connection
            repository = PostgresCRMContractsRepository(connection, business.scope.tenant_id)
            yield repository, business.scope.workspace_id
            return
        db_path = getattr(request.app.state, "db_path", None)
        if db_path is None:
            raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
        connection = sqlite3.connect(db_path)
        try:
            local_repository = SqliteCRMContractsRepository(connection)
            workspace_id = getattr(request.state, "workspace_id", "default")
            yield local_repository, workspace_id
        finally:
            connection.close()


def _verified_approval_role(
    repo: SqliteCRMContractsRepository | PostgresCRMContractsRepository, user: LocalUser, requested: str
) -> str:
    hierarchy = ("sales_rep", "sales_manager", "commercial_director", "vp_sales", "cfo", "admin")
    if isinstance(repo, PostgresCRMContractsRepository):
        roles = PostgresIdentityRepository(repo.connection).user_roles(tenant_id=repo.tenant_id, user_id=user.id)
    else:
        repo._conn.row_factory = sqlite3.Row
        roles = RoleRepository(repo._conn).user_roles(user.username)
    actual = next((role for role in reversed(hierarchy) if role in roles), "sales_rep")
    if hierarchy.index(requested) > hierarchy.index(actual):
        raise APIError(
            status_code=403,
            code="quotation_role_denied",
            message="The requested discount authority is not assigned to the authenticated reviewer.",
        )
    return actual


def _quotation_author_id(
    repo: SqliteCRMContractsRepository | PostgresCRMContractsRepository, workspace_id: str, quote_id: str
) -> str:
    """Only immutable creation provenance establishes the original human author."""
    author_id = repo.quotation_author_id(workspace_id, quote_id)
    if author_id is None:
        raise APIError(status_code=409, code="quotation_identity_unverified", message="The original submitter requires a reviewed immutable identity binding.")
    return author_id


class OpportunityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    opportunity_id: str = Field(min_length=1, max_length=64)
    organization_id: str = Field(min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=128)
    stage: OpportunityStage
    estimated_close_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    currency: str = Field(min_length=3, max_length=3)
    projected_amount_minor: int = Field(ge=0)
    win_probability_bps: int = Field(ge=0, le=10000)


class QuotationLinePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    line_number: int = Field(ge=1)
    item_id: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=128)
    quantity: int = Field(ge=1)
    unit_price_minor: int = Field(ge=0)
    discount_bps: int = Field(default=0, ge=0, le=10000)


class QuotationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    quote_id: str = Field(min_length=1, max_length=64)
    opportunity_id: str = Field(min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=64)
    currency: str = Field(min_length=3, max_length=3)
    valid_until: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    lines: list[QuotationLinePayload] = Field(min_length=1)


class QuoteApprovalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    approver_role: Literal["sales_rep", "sales_manager", "commercial_director", "vp_sales", "cfo", "admin"]


class ContractConversionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    contract_id: str = Field(min_length=1, max_length=64)
    organization_id: str = Field(min_length=1, max_length=64)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    billing_frequency: BillingFrequency
    as_of_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class ContractTerminationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    termination_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    early_termination_fee_minor: int = Field(ge=0)
    approver_id: str = Field(min_length=1, max_length=64)


# --- Opportunity Endpoints ---


@router.post("/opportunities")
def create_opportunity(user: Manage, payload: OpportunityPayload, request: Request) -> dict[str, object]:
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        try:
            opp = Opportunity(
                opportunity_id=payload.opportunity_id,
                workspace_id=ws_id,
                organization_id=payload.organization_id,
                customer_id=payload.customer_id,
                title=payload.title,
                stage=payload.stage,
                estimated_close_date=payload.estimated_close_date,
                currency=payload.currency,
                projected_amount_minor=payload.projected_amount_minor,
                win_probability_bps=payload.win_probability_bps,
            )
            repo.save_opportunity(opp)
        except FinancePostingError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "opportunity_id": opp.opportunity_id,
            "stage": opp.stage,
            "weighted_pipeline_value_minor": opp.weighted_pipeline_value_minor,
        }


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(user: Read, opportunity_id: str, request: Request) -> dict[str, object]:
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        opp = repo.get_opportunity(ws_id, opportunity_id)
        if not opp:
            raise APIError(
                status_code=404,
                code="opportunity_not_found",
                message=f"Opportunity {opportunity_id} not found",
            )
        return {
            "opportunity_id": opp.opportunity_id,
            "title": opp.title,
            "stage": opp.stage,
            "currency": opp.currency,
            "projected_amount_minor": opp.projected_amount_minor,
            "win_probability_bps": opp.win_probability_bps,
            "weighted_pipeline_value_minor": opp.weighted_pipeline_value_minor,
        }


# --- Quotation Endpoints ---


@router.post("/quotations")
def create_quotation(user: Manage, payload: QuotationPayload, request: Request) -> dict[str, object]:
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        lines = tuple(
            QuotationLineItem(
                line_number=line.line_number,
                item_id=line.item_id,
                description=line.description,
                quantity=line.quantity,
                unit_price_minor=line.unit_price_minor,
                discount_bps=line.discount_bps,
            )
            for line in payload.lines
        )
        try:
            quote = CustomerQuotation(
                quote_id=payload.quote_id,
                opportunity_id=payload.opportunity_id,
                workspace_id=ws_id,
                customer_id=payload.customer_id,
                currency=payload.currency,
                valid_until=payload.valid_until,
                submitter_user_id=user.id,
                status="draft",
                lines=lines,
            )
            repo.save_quotation(quote, author_user_id=user.id)
        except FinancePostingError as exc:
            raise APIError(status_code=409 if exc.code == "crm_quotation_exists" else 400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "quote_id": quote.quote_id,
            "total_gross_minor": quote.total_gross_minor,
            "total_discount_minor": quote.total_discount_minor,
            "total_net_minor": quote.total_net_minor,
            "effective_discount_bps": quote.effective_discount_bps,
        }


@router.get("/quotations/{quote_id}")
def get_quotation(user: Read, quote_id: str, request: Request) -> dict[str, object]:
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        quote = repo.get_quotation(ws_id, quote_id)
        if not quote:
            raise APIError(
                status_code=404,
                code="quotation_not_found",
                message=f"Quotation {quote_id} not found",
            )
        return {
            "quote_id": quote.quote_id,
            "opportunity_id": quote.opportunity_id,
            "customer_id": quote.customer_id,
            "currency": quote.currency,
            "valid_until": quote.valid_until,
            "status": quote.status,
            "submitter_user_id": quote.submitter_user_id,
            "approved_by_user_id": quote.approved_by_user_id,
            "total_net_minor": quote.total_net_minor,
            "effective_discount_bps": quote.effective_discount_bps,
        }


@router.post("/quotations/{quote_id}/approve")
def approve_quotation(
    user: Approve, quote_id: str, payload: QuoteApprovalPayload, request: Request
) -> dict[str, object]:
    with _repo(request, permissions=frozenset({"sales.approve"}), permission_mode="all") as ((repo, ws_id)):
        quote = repo.get_quotation(ws_id, quote_id)
        if not quote:
            raise APIError(
                status_code=404,
                code="quotation_not_found",
                message=f"Quotation {quote_id} not found",
            )

        try:
            if _quotation_author_id(repo, ws_id, quote.quote_id) == user.id:
                raise FinancePostingError("crm_sod_violation", "Submitter cannot approve their own quotation.")
            approved = quote.approve(
                approver_user_id=user.id,
                approver_role=_verified_approval_role(repo, user, payload.approver_role),
            )
            repo.save_quotation(approved)
        except FinancePostingError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "quote_id": approved.quote_id,
            "quote_status": approved.status,
            "approved_by": user.username,
            "approved_by_user_id": approved.approved_by_user_id,
        }


@router.post("/quotations/{quote_id}/convert")
def convert_quotation(
    user: Manage, quote_id: str, payload: ContractConversionPayload, request: Request
) -> dict[str, object]:
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        quote = repo.get_quotation(ws_id, quote_id)
        if not quote:
            raise APIError(
                status_code=404,
                code="quotation_not_found",
                message=f"Quotation {quote_id} not found",
            )

        _quotation_author_id(repo, ws_id, quote.quote_id)
        try:
            contract = convert_quote_to_contract(
                quote=quote,
                contract_id=payload.contract_id,
                organization_id=payload.organization_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                billing_frequency=payload.billing_frequency,
                as_of_date=payload.as_of_date,
            )
            repo.save_contract(contract)
        except FinancePostingError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "contract_id": contract.contract_id,
            "total_contract_value_minor": contract.total_contract_value_minor,
            "contract_status": contract.status,
        }


# --- Contract Endpoints ---


@router.get("/contracts/{contract_id}")
def get_contract(user: Read, contract_id: str, request: Request) -> dict[str, object]:
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        contract = repo.get_contract(ws_id, contract_id)
        if not contract:
            raise APIError(
                status_code=404,
                code="contract_not_found",
                message=f"Contract {contract_id} not found",
            )
        return {
            "contract_id": contract.contract_id,
            "quote_id": contract.quote_id,
            "customer_id": contract.customer_id,
            "currency": contract.currency,
            "start_date": contract.start_date,
            "end_date": contract.end_date,
            "billing_frequency": contract.billing_frequency,
            "total_contract_value_minor": contract.total_contract_value_minor,
            "status": contract.status,
        }


@router.post("/contracts/{contract_id}/terminate")
def terminate_contract_endpoint(
    user: Manage, contract_id: str, payload: ContractTerminationPayload, request: Request
) -> dict[str, object]:
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        raise APIError(
            status_code=403,
            code="termination_review_required",
            message="Contract termination requires a persisted independent approval; a caller-supplied approver label is not sufficient.",
        )


class ContractSuspendPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reason: str = Field(min_length=1, max_length=500)


class ContractRenewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    new_end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    price_adjustment_bps: int = Field(ge=-10000, le=100000)


class SubscriptionPlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=3, max_length=3)
    billing_interval: BillingFrequency
    unit_price_minor: int = Field(ge=0)


class SubscriptionCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    subscription_id: str = Field(min_length=1, max_length=64)
    customer_id: str = Field(min_length=1, max_length=64)
    contract_id: str = Field(min_length=1, max_length=64)
    plan_id: str = Field(min_length=1, max_length=64)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal["active", "paused", "cancelled", "expired"] = "active"
    current_period_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    current_period_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    auto_renew: bool = True


class SubscriptionProrationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    old_plan_id: str = Field(min_length=1, max_length=64)
    new_plan_id: str = Field(min_length=1, max_length=64)
    period_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    change_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class SubscriptionCancelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cancellation_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/contracts/{contract_id}/suspend")
def suspend_contract_endpoint(
    user: Manage, contract_id: str, payload: ContractSuspendPayload, request: Request
) -> dict[str, object]:
    """Suspends an active customer contract."""
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        contract = repo.get_contract(ws_id, contract_id)
        if not contract:
            raise APIError(status_code=404, code="contract_not_found", message=f"Contract {contract_id} not found")
        try:
            suspended = suspend_contract(contract, reason=payload.reason, actor_id=user.id)
            repo.save_contract(suspended)
        except FinancePostingError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
        return {
            "status": "success",
            "contract_id": suspended.contract_id,
            "contract_status": suspended.status,
        }


@router.post("/contracts/{contract_id}/resume")
def resume_contract_endpoint(user: Manage, contract_id: str, request: Request) -> dict[str, object]:
    """Resumes a suspended customer contract."""
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        contract = repo.get_contract(ws_id, contract_id)
        if not contract:
            raise APIError(status_code=404, code="contract_not_found", message=f"Contract {contract_id} not found")
        try:
            resumed = resume_contract(contract, actor_id=user.id)
            repo.save_contract(resumed)
        except FinancePostingError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
        return {
            "status": "success",
            "contract_id": resumed.contract_id,
            "contract_status": resumed.status,
        }


@router.post("/contracts/{contract_id}/renew")
def renew_contract_endpoint(
    user: Approve, contract_id: str, payload: ContractRenewPayload, request: Request
) -> dict[str, object]:
    """Renews a customer contract with price adjustments in basis points."""
    with _repo(request, permissions=frozenset({"sales.approve"}), permission_mode="all") as ((repo, ws_id)):
        contract = repo.get_contract(ws_id, contract_id)
        if not contract:
            raise APIError(status_code=404, code="contract_not_found", message=f"Contract {contract_id} not found")
        try:
            renewed = renew_contract(
                contract,
                new_end_date=payload.new_end_date,
                price_adjustment_bps=payload.price_adjustment_bps,
                approver_id=user.id,
            )
            repo.save_contract(renewed)
        except FinancePostingError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
        return {
            "status": "success",
            "contract_id": renewed.contract_id,
            "contract_status": renewed.status,
            "new_end_date": renewed.end_date,
            "total_contract_value_minor": renewed.total_contract_value_minor,
        }


# --- Subscription Endpoints ---


@router.post("/subscriptions/plans")
def create_subscription_plan(user: Manage, payload: SubscriptionPlanPayload, request: Request) -> dict[str, object]:
    """Creates a new recurring subscription plan."""
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        try:
            plan = SubscriptionPlan(
                plan_id=payload.plan_id,
                name=payload.name,
                currency=payload.currency,
                billing_interval=payload.billing_interval,
                unit_price_minor=payload.unit_price_minor,
            )
            repo.save_plan(ws_id, plan)
        except FinancePostingError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
        return {
            "status": "success",
            "plan_id": plan.plan_id,
            "name": plan.name,
            "currency": plan.currency,
            "billing_interval": plan.billing_interval,
            "unit_price_minor": plan.unit_price_minor,
        }


@router.get("/subscriptions/plans/{plan_id}")
def get_subscription_plan(user: Read, plan_id: str, request: Request) -> dict[str, object]:
    """Retrieves subscription plan by plan_id."""
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        plan = repo.get_plan(ws_id, plan_id)
        if not plan:
            raise APIError(status_code=404, code="plan_not_found", message=f"Subscription plan {plan_id} not found")
        return {
            "plan_id": plan.plan_id,
            "name": plan.name,
            "currency": plan.currency,
            "billing_interval": plan.billing_interval,
            "unit_price_minor": plan.unit_price_minor,
        }


@router.get("/subscriptions/plans")
def list_subscription_plans(user: Read, request: Request) -> dict[str, object]:
    """Lists all subscription plans in workspace."""
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        plans = repo.list_plans(ws_id)
        return {
            "plans": [
                {
                    "plan_id": p.plan_id,
                    "name": p.name,
                    "currency": p.currency,
                    "billing_interval": p.billing_interval,
                    "unit_price_minor": p.unit_price_minor,
                }
                for p in plans
            ]
        }


@router.post("/subscriptions")
def create_subscription(user: Manage, payload: SubscriptionCreatePayload, request: Request) -> dict[str, object]:
    """Creates an active recurring customer subscription."""
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        plan = repo.get_plan(ws_id, payload.plan_id)
        if not plan:
            raise APIError(status_code=400, code="plan_not_found", message=f"Plan {payload.plan_id} does not exist.")
        try:
            sub = Subscription(
                subscription_id=payload.subscription_id,
                customer_id=payload.customer_id,
                contract_id=payload.contract_id,
                plan_id=payload.plan_id,
                currency=payload.currency,
                status=payload.status,
                current_period_start=payload.current_period_start,
                current_period_end=payload.current_period_end,
                auto_renew=payload.auto_renew,
            )
            repo.save_subscription(ws_id, sub)
        except FinancePostingError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc
        return {
            "status": "success",
            "subscription_id": sub.subscription_id,
            "customer_id": sub.customer_id,
            "contract_id": sub.contract_id,
            "plan_id": sub.plan_id,
            "currency": sub.currency,
            "subscription_status": sub.status,
            "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end,
            "auto_renew": sub.auto_renew,
        }


@router.get("/subscriptions/{subscription_id}")
def get_subscription_endpoint(user: Read, subscription_id: str, request: Request) -> dict[str, object]:
    """Retrieves customer subscription details."""
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        sub = repo.get_subscription(ws_id, subscription_id)
        if not sub:
            raise APIError(
                status_code=404, code="subscription_not_found", message=f"Subscription {subscription_id} not found"
            )
        return {
            "subscription_id": sub.subscription_id,
            "customer_id": sub.customer_id,
            "contract_id": sub.contract_id,
            "plan_id": sub.plan_id,
            "currency": sub.currency,
            "subscription_status": sub.status,
            "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end,
            "auto_renew": sub.auto_renew,
        }


@router.get("/subscriptions")
def list_subscriptions_endpoint(user: Read, request: Request, customer_id: str | None = None) -> dict[str, object]:
    """Lists customer subscriptions."""
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        subs = repo.list_subscriptions(ws_id, customer_id=customer_id)
        return {
            "subscriptions": [
                {
                    "subscription_id": s.subscription_id,
                    "customer_id": s.customer_id,
                    "contract_id": s.contract_id,
                    "plan_id": s.plan_id,
                    "currency": s.currency,
                    "subscription_status": s.status,
                    "current_period_start": s.current_period_start,
                    "current_period_end": s.current_period_end,
                    "auto_renew": s.auto_renew,
                }
                for s in subs
            ]
        }


@router.post("/subscriptions/proration")
def prorate_subscription_plan_change(
    user: Read, payload: SubscriptionProrationPayload, request: Request
) -> dict[str, object]:
    """Computes zero-float day-prorated charges and credits for a mid-cycle plan change."""
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        old_plan = repo.get_plan(ws_id, payload.old_plan_id)
        new_plan = repo.get_plan(ws_id, payload.new_plan_id)
        if not old_plan:
            raise APIError(status_code=404, code="plan_not_found", message=f"Old plan {payload.old_plan_id} not found")
        if not new_plan:
            raise APIError(status_code=404, code="plan_not_found", message=f"New plan {payload.new_plan_id} not found")

        try:
            result = calculate_plan_change_proration(
                old_plan=old_plan,
                new_plan=new_plan,
                period_start=payload.period_start,
                period_end=payload.period_end,
                change_date=payload.change_date,
            )
        except FinancePostingError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "old_plan_id": old_plan.plan_id,
            "new_plan_id": new_plan.plan_id,
            "currency": old_plan.currency,
            **result,
        }


@router.post("/subscriptions/{subscription_id}/cancel")
def cancel_subscription_endpoint(
    user: Manage, subscription_id: str, payload: SubscriptionCancelPayload, request: Request
) -> dict[str, object]:
    """Cancels an active subscription and calculates exact refundable credit."""
    with _repo(request, permissions=frozenset({"sales.manage"}), permission_mode="all") as ((repo, ws_id)):
        sub = repo.get_subscription(ws_id, subscription_id)
        if not sub:
            raise APIError(
                status_code=404, code="subscription_not_found", message=f"Subscription {subscription_id} not found"
            )
        plan = repo.get_plan(ws_id, sub.plan_id)
        if not plan:
            raise APIError(status_code=400, code="plan_not_found", message=f"Plan {sub.plan_id} not found")

        try:
            cancelled, refund_minor = cancel_subscription_with_refund(
                subscription=sub,
                plan=plan,
                cancellation_date=payload.cancellation_date,
            )
            repo.save_subscription(ws_id, cancelled)
        except FinancePostingError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "subscription_id": cancelled.subscription_id,
            "subscription_status": cancelled.status,
            "refund_minor": refund_minor,
        }
