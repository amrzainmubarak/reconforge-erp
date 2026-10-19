"""FastAPI routes for CRM Opportunities, Quotations, and Customer Contracts."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.domain.crm_contracts import (
    BillingFrequency,
    CustomerQuotation,
    Opportunity,
    OpportunityStage,
    QuotationLineItem,
    convert_quote_to_contract,
    terminate_contract,
)
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.sqlite_crm_contracts import (
    SqliteCRMContractsRepository,
)

router = APIRouter(prefix="/crm/contracts", tags=["crm-contracts"])
Read = Annotated[LocalUser, Depends(require_permission("sales.manage"))]
Manage = Annotated[LocalUser, Depends(require_permission("sales.manage"))]
Approve = Annotated[LocalUser, Depends(require_permission("sales.approve"))]


def _repo(request: Request) -> tuple[SqliteCRMContractsRepository, str]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
    conn = sqlite3.connect(db_path)
    workspace_id = getattr(request.state, "workspace_id", "default")
    return SqliteCRMContractsRepository(conn), workspace_id


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
    repo, ws_id = _repo(request)
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
    repo, ws_id = _repo(request)
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
    repo, ws_id = _repo(request)
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
            submitter_user_id=user.username,
            status="draft",
            lines=lines,
        )
        repo.save_quotation(quote)
    except FinancePostingError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

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
    repo, ws_id = _repo(request)
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
    repo, ws_id = _repo(request)
    quote = repo.get_quotation(ws_id, quote_id)
    if not quote:
        raise APIError(
            status_code=404,
            code="quotation_not_found",
            message=f"Quotation {quote_id} not found",
        )

    try:
        approved = quote.approve(
            approver_user_id=user.username,
            approver_role=payload.approver_role,
        )
        repo.save_quotation(approved)
    except FinancePostingError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

    return {
        "status": "success",
        "quote_id": approved.quote_id,
        "quote_status": approved.status,
        "approved_by": approved.approved_by_user_id,
    }


@router.post("/quotations/{quote_id}/convert")
def convert_quotation(
    user: Manage, quote_id: str, payload: ContractConversionPayload, request: Request
) -> dict[str, object]:
    repo, ws_id = _repo(request)
    quote = repo.get_quotation(ws_id, quote_id)
    if not quote:
        raise APIError(
            status_code=404,
            code="quotation_not_found",
            message=f"Quotation {quote_id} not found",
        )

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
    repo, ws_id = _repo(request)
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
    repo, ws_id = _repo(request)
    contract = repo.get_contract(ws_id, contract_id)
    if not contract:
        raise APIError(
            status_code=404,
            code="contract_not_found",
            message=f"Contract {contract_id} not found",
        )

    try:
        terminated, fee = terminate_contract(
            contract=contract,
            termination_date=payload.termination_date,
            early_termination_fee_minor=payload.early_termination_fee_minor,
            actor_id=user.username,
            approver_id=payload.approver_id,
        )
        repo.save_contract(terminated)
    except FinancePostingError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

    return {
        "status": "success",
        "contract_id": terminated.contract_id,
        "contract_status": terminated.status,
        "early_termination_fee_minor": fee,
    }
