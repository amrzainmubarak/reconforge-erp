"""Typed scoped pre-stock demand, native sourcing, receipt/AP and atomic handoff."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.manufacturing_execution import OrderRequest, PhaseRequest, scope_fields
from reconforge.api.routes.manufacturing_execution_v2 import CostClaim
from reconforge.api.routes.procurement_operations import required
from reconforge.api.routes.procurement_partial import (
    LineReceiptRequest,
    MultilineInvoiceRequest,
    MultilineOrderRequest,
    PartialActionRequest,
)
from reconforge.api.routes.procurement_sourcing import AwardRequest, QuotationRequest, SourcingCommandRequest
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.application.manufacturing_supply_plan import ManufacturingSupplyPlanService
from reconforge.auth.models import LocalUser
from reconforge.domain.budget_control import BudgetControlError
from reconforge.domain.finance_posting import FinancePostingError, PostingActor, digest_payload
from reconforge.domain.inventory_receipt_posting import InventoryReceiptPostingError
from reconforge.domain.manufacturing_execution import OrderPreparation
from reconforge.domain.manufacturing_execution_v2 import ManufacturingOrderPreparation
from reconforge.domain.manufacturing_supply_plan import PERMISSIONS, READ, SupplyPlanPreparation
from reconforge.domain.procurement_partial import (
    MultilineInvoicePreparation,
    MultilineProcurementPreparation,
    PartialQuantityPreparation,
    ProcurementLineQuantity,
    ProcurementOrderLine,
)
from reconforge.domain.procurement_sourcing import RequisitionPreparation, SupplierQuotationPreparation
from reconforge.infrastructure.postgres_manufacturing_supply_plan import PostgresManufacturingSupplyPlanRepository
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/manufacturing-supply-plan", tags=["manufacturing-supply-plan"])
Read = Annotated[LocalUser, Depends(required(READ))]
Create = Annotated[LocalUser, Depends(required(PERMISSIONS["create"]))]
Approve = Annotated[LocalUser, Depends(required(PERMISSIONS["approve"]))]
Cancel = Annotated[LocalUser, Depends(required(PERMISSIONS["cancel"]))]
Handoff = Annotated[LocalUser, Depends(required(PERMISSIONS["handoff"]))]


class PriceCeiling(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    item_code: str = Field(min_length=1, max_length=64)
    unit_price_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")


class PlanRequest(OrderRequest):
    routing_id: str = Field(min_length=1, max_length=160)
    budget_id: str = Field(min_length=1, max_length=160)
    unit_price_ceilings_minor: list[PriceCeiling] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_components(self) -> PlanRequest:
        if len({line.item_code.strip() for line in self.unit_price_ceilings_minor}) != len(self.unit_price_ceilings_minor):
            raise ValueError("Price ceiling components must be distinct.")
        return self


class PlannedRequisitionRequest(MultilineOrderRequest):
    command_id: str = Field(min_length=1, max_length=140)
    number: str = Field(pattern=r"^SRC5-MSP-[A-F0-9]{16}$")
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    budget_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=500)
    requirement_ids: list[str] = Field(min_length=1, max_length=100)


class HandoffRequest(PhaseRequest):
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    claims: list[CostClaim] = Field(min_length=1, max_length=100)


class PostInvoiceRequest(PartialActionRequest):
    command_id: str = Field(min_length=1, max_length=140)
    document_id: str = Field(min_length=1, max_length=160)
    expected_budget_version: int = Field(ge=1, le=9_000_000_000_000_000_000)


class SupplyActionRequest(PartialActionRequest):
    command_id: str = Field(min_length=1, max_length=140)


class SupplyReceiptRequest(LineReceiptRequest):
    command_id: str = Field(min_length=1, max_length=140)


class SupplyInvoiceRequest(MultilineInvoiceRequest):
    command_id: str = Field(min_length=1, max_length=140)


def project_supply(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        if key == "unit_price_ceilings_minor":
            return {name: str(item) for name, item in value.items()}
        return {name: project_supply(item, name) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value] if key == "unit_prices_minor" else [project_supply(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if type(value) is int and (key.endswith(("_minor", "_scaled")) or abs(value) > 9_007_199_254_740_991):
        return str(value)
    return value


def execute(request: Request, user: LocalUser,
            action: Callable[[ManufacturingSupplyPlanService, PostingActor, FinanceCoreExecutionScope], Any],
            *, payload: BaseModel | None = None) -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="manufacturing_supply_backend_unavailable", message="Native supply custody requires PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        if scope.organization_id is None or scope.legal_entity_id is None:
            raise APIError(status_code=403, code="manufacturing_supply_scope_required", message="Select an authorized organization and legal entity.")
        try:
            repository = PostgresManufacturingSupplyPlanRepository(finance.connection, scope.tenant_id)
            result = action(ManufacturingSupplyPlanService(repository), actor, scope)
            projected = project_supply(result)
            if payload is not None:
                submitted = payload.model_dump(mode="json", exclude_unset=True)
                receipt = repository.command_receipt(result["source"]["id"], str(submitted["command_id"]), result, actor=actor)
                # Seal the exact public projection of the original stored ACK;
                # original native request digest remains separately verifiable.
                projected["command_ack"] = {**project_supply(receipt), "response_digest": digest_payload(projected)}
                projected["submitted_request"] = submitted
                projected["submitted_request_digest"] = digest_payload(submitted)
            return projected
        except (FinancePostingError, InventoryReceiptPostingError) as exc:
            raise APIError(status_code=403 if "denied" in exc.code else 404 if "not_found" in exc.code else 409, code=exc.code, message=str(exc)) from exc
        except BudgetControlError as exc:
            raise APIError(status_code=403 if any(word in str(exc).lower() for word in ("authority", "permission", "authentication", "assurance")) else 409,
                code="manufacturing_supply_budget_conflict", message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="manufacturing_supply_state_conflict", message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.get("/plans")
def list_plans(request: Request, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.list_plans(scope_fields(scope), actor=actor))


@router.get("/plans/{identifier}")
def get_plan(request: Request, identifier: str, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: {"source": service.get(identifier, actor=actor)})


@router.get("/requirements/{identifier}")
def get_requirement(request: Request, identifier: str, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: {"requirement": service.get_requirement(identifier, actor=actor)})


@router.post("/plans")
def create_plan(request: Request, payload: PlanRequest, user: Create) -> dict[str, Any]:
    def invoke(service: ManufacturingSupplyPlanService, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        material = OrderPreparation(**payload.model_dump(exclude={"command_id", "routing_id", "budget_id", "unit_price_ceilings_minor"}), **scope_fields(scope))
        prepared = SupplyPlanPreparation(material, payload.routing_id, payload.budget_id,
            {line.item_code: int(line.unit_price_minor) for line in payload.unit_price_ceilings_minor})
        return service.create(prepared, command_id=payload.command_id, actor=actor)
    return execute(request, user, invoke, payload=payload)


@router.post("/plans/{identifier}/approve")
def approve_plan(request: Request, identifier: str, payload: PhaseRequest, user: Approve) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.approve(identifier, **payload.model_dump(), actor=actor), payload=payload)


@router.post("/plans/{identifier}/cancel")
def cancel_plan(request: Request, identifier: str, payload: PhaseRequest, user: Cancel) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.cancel(identifier, **payload.model_dump(), actor=actor), payload=payload)


@router.post("/plans/{identifier}/handoff")
def handoff_plan(request: Request, identifier: str, payload: HandoffRequest, user: Handoff) -> dict[str, Any]:
    def invoke(service: ManufacturingSupplyPlanService, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        source = service.get(identifier, actor=actor)
        material = OrderPreparation(**{key: value for key, value in source["command_request"]["material"].items() if key != "schema_version"})
        prepared = ManufacturingOrderPreparation(replace(material, posting_date=payload.posting_date), source["routing_id"],
            [claim.claim_payload() for claim in payload.claims])
        return service.handoff(identifier, prepared, **payload.model_dump(exclude={"posting_date", "claims"}), actor=actor)
    return execute(request, user, invoke, payload=payload)


@router.get("/plans/{identifier}/requisitions/{requisition_id}")
def get_requisition(request: Request, identifier: str, requisition_id: str, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.get_requisition(identifier, requisition_id, actor=actor))


@router.get("/plans/{identifier}/purchases/{order_id}")
def get_purchase(request: Request, identifier: str, order_id: str, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.get_purchase(identifier, order_id, actor=actor))


@router.post("/plans/{identifier}/requisitions")
def create_requisition(request: Request, identifier: str, payload: PlannedRequisitionRequest,
                       user: LocalUser = Depends(required(PERMISSIONS["source-create"]))) -> dict[str, Any]:
    def invoke(service: ManufacturingSupplyPlanService, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        if (payload.workspace not in {"default", scope.workspace_id} or payload.organization_code != scope.organization_code
                or payload.entity_code != scope.entity_code):
            raise APIError(status_code=403, code="manufacturing_supply_scope_alias_denied",
                message="Purchase scope aliases must match the current selected original hierarchy.")
        fields = payload.model_dump(exclude={"command_id", "expected_digest", "requirement_ids", "budget_id", "reason", "lines", "workspace", "organization_code", "entity_code"})
        order = MultilineProcurementPreparation(**fields, workspace=scope.workspace_id, organization_code=scope.organization_code, entity_code=scope.entity_code,
            lines=tuple(ProcurementOrderLine(**{**line.model_dump(), "unit_price_minor": int(line.unit_price_minor)}) for line in payload.lines))
        return service.create_requisition(identifier, RequisitionPreparation(budget_id=payload.budget_id, order=order, reason=payload.reason),
            requirement_ids=tuple(payload.requirement_ids), expected_digest=payload.expected_digest, command_id=payload.command_id, actor=actor)
    return execute(request, user, invoke, payload=payload)


@router.post("/plans/{identifier}/requisitions/{requisition_id}/quote")
def quote(request: Request, identifier: str, requisition_id: str, payload: QuotationRequest,
          user: LocalUser = Depends(required(PERMISSIONS["source-quote"]))) -> dict[str, Any]:
    quotation = SupplierQuotationPreparation(supplier_code=payload.supplier_code, unit_prices_minor=tuple(int(value) for value in payload.unit_prices_minor),
        valid_until=payload.valid_until, reason=payload.reason)
    return execute(request, user, lambda service, actor, scope: service.act_requisition(identifier, requisition_id, "quote",
        expected_version=payload.expected_version, command_id=payload.command_id, reason=payload.reason, actor=actor, quotation=quotation), payload=payload)


@router.post("/plans/{identifier}/requisitions/{requisition_id}/award")
def award(request: Request, identifier: str, requisition_id: str, payload: AwardRequest,
          user: LocalUser = Depends(required(PERMISSIONS["source-award"]))) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.act_requisition(identifier, requisition_id, "award", **payload.model_dump(), actor=actor), payload=payload)


def source_endpoint(operation: str) -> Callable[..., dict[str, Any]]:
    def endpoint(request: Request, identifier: str, requisition_id: str, payload: SourcingCommandRequest,
                 user: LocalUser = Depends(required(PERMISSIONS["source-" + operation]))) -> dict[str, Any]:
        return execute(request, user, lambda service, actor, scope: service.act_requisition(identifier, requisition_id, operation, **payload.model_dump(), actor=actor), payload=payload)
    endpoint.__name__ = "supply_source_" + operation.replace("-", "_")
    return endpoint


for operation in ("open-rfq", "review-selection", "cancel"):
    router.add_api_route("/plans/{identifier}/requisitions/{requisition_id}/" + operation, source_endpoint(operation), methods=["POST"])


@router.post("/plans/{identifier}/purchases/{order_id}/receive-prepare")
def prepare_receipt(request: Request, identifier: str, order_id: str, payload: SupplyReceiptRequest,
                    user: LocalUser = Depends(required(PERMISSIONS["receive-prepare"]))) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.procurement_operation(identifier, order_id, "receive-prepare",
        expected_version=payload.expected_version, command_id=payload.command_id, reason=payload.reason, line_id=payload.line_id, actor=actor,
        quantity_request=PartialQuantityPreparation(**payload.model_dump(exclude={"command_id", "expected_version", "line_id"}))), payload=payload)


@router.post("/plans/{identifier}/purchases/{order_id}/invoice-match")
def match_invoice(request: Request, identifier: str, order_id: str, payload: SupplyInvoiceRequest,
                  user: LocalUser = Depends(required(PERMISSIONS["invoice-match"]))) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.procurement_operation(identifier, order_id, "invoice-match",
        expected_version=payload.expected_version, command_id=payload.command_id, reason=payload.reason, actor=actor,
        invoice_request=MultilineInvoicePreparation(**payload.model_dump(exclude={"command_id", "expected_version", "lines"}),
            lines=tuple(ProcurementLineQuantity(**line.model_dump()) for line in payload.lines))), payload=payload)


@router.post("/plans/{identifier}/purchases/{order_id}/invoice-post")
def post_invoice(request: Request, identifier: str, order_id: str, payload: PostInvoiceRequest,
                 user: LocalUser = Depends(required(PERMISSIONS["invoice-post"]))) -> dict[str, Any]:
    return execute(request, user, lambda service, actor, scope: service.procurement_operation(identifier, order_id, "invoice-post", **payload.model_dump(), actor=actor), payload=payload)


def purchase_endpoint(operation: str) -> Callable[..., dict[str, Any]]:
    def endpoint(request: Request, identifier: str, order_id: str, payload: SupplyActionRequest,
                 user: LocalUser = Depends(required(PERMISSIONS[operation]))) -> dict[str, Any]:
        return execute(request, user, lambda service, actor, scope: service.procurement_operation(identifier, order_id, operation, **payload.model_dump(), actor=actor), payload=payload)
    endpoint.__name__ = "supply_purchase_" + operation.replace("-", "_")
    return endpoint


for operation in ("purchase-submit", "purchase-approve", "receive-review", "receive-commit", "invoice-approve", "invoice-prepare", "invoice-review"):
    router.add_api_route("/plans/{identifier}/purchases/{order_id}/" + operation, purchase_endpoint(operation), methods=["POST"])
