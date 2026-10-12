"""Real current-human PR, RFQ, quotations and atomic native purchase awards."""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

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
from reconforge.domain.procurement_partial import MultilineProcurementPreparation, ProcurementOrderLine
from reconforge.domain.procurement_sourcing import (
    PERMISSIONS,
    RequirementReference,
    RequisitionPreparation,
    SupplierQuotationPreparation,
)
from reconforge.infrastructure.postgres_procurement_operations import PostgresProcurementOperationsRepository
from reconforge.infrastructure.postgres_procurement_sourcing import PostgresProcurementSourcingRepository

router = APIRouter(prefix="/procurement-sourcing", tags=["procurement-sourcing"])
READ = PERMISSIONS["read"]


class RequirementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    requirement_id: str = Field(min_length=1, max_length=160)
    requirement_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class RequisitionRequest(MultilineOrderRequest):
    budget_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=500)
    requirements: list[RequirementRequest | None] = Field(default_factory=list, max_length=128)


class SourcingCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    expected_version: int = Field(ge=1, le=38)
    reason: str = Field(min_length=1, max_length=500)


class AwardRequest(SourcingCommandRequest):
    expected_budget_version: int = Field(ge=1, le=9_000_000_000_000_000_000)


class QuotationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    expected_version: int = Field(ge=1, le=38)
    supplier_code: str = Field(min_length=1, max_length=64)
    unit_prices_minor: list[Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]] = Field(min_length=1, max_length=128)
    valid_until: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(min_length=1, max_length=500)


def _execute(request: Request, user: LocalUser, permissions: frozenset[str],
             operation: Callable[[PostgresProcurementSourcingRepository, PostingActor, FinanceCoreExecutionScope], Any],
             *, organization_code: str = "", entity_code: str = "") -> Any:
    def invoke(shared: PostgresProcurementOperationsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Any:
        try:
            return operation(PostgresProcurementSourcingRepository(shared.connection, scope.tenant_id,
                require_live_session_assurance=True), actor, scope)
        except BudgetControlError as exc:
            message = str(exc).lower()
            if "stronger authentication" in message or "session assurance" in message:
                raise APIError(status_code=403, code="step_up_required", message=str(exc)) from exc
            denied = any(word in message for word in ("authority", "permission", "identity", "authentication", "session", "assurance"))
            raise APIError(status_code=403 if denied else 409, code="procurement_sourcing_denied" if denied else "procurement_sourcing_conflict", message=str(exc)) from exc
    return execute(request, user, permissions, invoke, organization_code=organization_code, entity_code=entity_code)


@router.post("/requisitions")
def create(request: Request, payload: RequisitionRequest,
           user: LocalUser = Depends(required(READ | PERMISSIONS["create"]))) -> dict[str, Any]:
    selected = request_execution_scope(request)
    if payload.workspace not in {"default", selected.workspace_id}:
        raise APIError(status_code=403, code="workspace_scope_denied", message="Workspace is outside current authority.")
    def run(repository: PostgresProcurementSourcingRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        header = payload.model_dump(exclude={"command_id", "lines", "workspace", "organization_code", "entity_code", "budget_id", "reason", "requirements"})
        order = MultilineProcurementPreparation(**header, workspace=scope.workspace_id, organization_code=scope.organization_code,
            entity_code=scope.entity_code, lines=tuple(ProcurementOrderLine(**{**line.model_dump(), "unit_price_minor": int(line.unit_price_minor)}) for line in payload.lines))
        references = tuple(RequirementReference(**reference.model_dump()) if reference else None for reference in payload.requirements)
        return repository.create(RequisitionPreparation(budget_id=payload.budget_id, order=order, requirements=references,
            reason=payload.reason), command_id=payload.command_id, actor=actor)
    return _execute(request, user, READ | PERMISSIONS["create"], run, organization_code=payload.organization_code, entity_code=payload.entity_code)


@router.get("/requisitions")
def list_requisitions(request: Request, user: LocalUser = Depends(required(READ))) -> dict[str, Any]:
    return _execute(request, user, READ, lambda repository, actor, scope: repository.list_requisitions(scope.workspace_id, actor=actor))


@router.get("/requisitions/{identifier}")
def get(request: Request, identifier: str, user: LocalUser = Depends(required(READ))) -> dict[str, Any]:
    return _execute(request, user, READ, lambda repository, actor, scope: repository.get(identifier, actor=actor))


@router.post("/requisitions/{identifier}/quotes")
def quote(request: Request, identifier: str, payload: QuotationRequest,
          user: LocalUser = Depends(required(READ | PERMISSIONS["quote"]))) -> dict[str, Any]:
    prepared = SupplierQuotationPreparation(supplier_code=payload.supplier_code,
        unit_prices_minor=tuple(int(price) for price in payload.unit_prices_minor), valid_until=payload.valid_until, reason=payload.reason)
    return _execute(request, user, READ | PERMISSIONS["quote"], lambda repository, actor, scope:
        repository.record_quotation(identifier, prepared, expected_version=payload.expected_version, command_id=payload.command_id, actor=actor))


@router.post("/requisitions/{identifier}/award")
def award(request: Request, identifier: str, payload: AwardRequest,
          user: LocalUser = Depends(required(READ | PERMISSIONS["award"]))) -> dict[str, Any]:
    return _execute(request, user, READ | PERMISSIONS["award"], lambda repository, actor, scope:
        repository.act(identifier, "award", **payload.model_dump(), actor=actor))


def _endpoint(operation: str) -> Callable[..., dict[str, Any]]:
    permissions = READ | PERMISSIONS[operation]
    def endpoint(request: Request, identifier: str, payload: SourcingCommandRequest,
                 user: LocalUser = Depends(required(permissions))) -> dict[str, Any]:
        return _execute(request, user, permissions, lambda repository, actor, scope:
            repository.act(identifier, operation, **payload.model_dump(), actor=actor))
    endpoint.__name__ = "procurement_sourcing_" + operation.replace("-", "_")
    return endpoint


for operation in ("open-rfq", "review-selection", "cancel"):
    router.add_api_route("/requisitions/{identifier}/" + operation, _endpoint(operation), methods=["POST"])
