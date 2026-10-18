"""Actual source-owned engineering, cost allocation, holds and quality commands."""
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.manufacturing_execution import (
    OrderRequest,
    PhaseRequest,
    StrictRequest,
    project,
    scope_fields,
)
from reconforge.api.routes.procurement_operations import required
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.application.manufacturing_execution_v2 import ManufacturingExecutionV2Service
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.inventory_receipt_posting import InventoryReceiptPostingError
from reconforge.domain.manufacturing_execution import OrderPreparation
from reconforge.domain.manufacturing_execution_v2 import (
    PERMISSIONS,
    READ,
    ManufacturingOrderPreparation,
    RoutingPreparation,
    WorkcenterPreparation,
)
from reconforge.infrastructure.postgres_manufacturing_execution_v2 import PostgresManufacturingExecutionV2Repository
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/manufacturing-execution-v2", tags=["manufacturing-execution-v2"])
Read = Annotated[LocalUser, Depends(required(READ))]
Create = Annotated[LocalUser, Depends(required(PERMISSIONS["create"]))]
Manage = Annotated[LocalUser, Depends(required(PERMISSIONS["prepare"]))]
Approve = Annotated[LocalUser, Depends(required(PERMISSIONS["approve"]))]
Review = Annotated[LocalUser, Depends(required(PERMISSIONS["review"]))]
Post = Annotated[LocalUser, Depends(required(PERMISSIONS["post"]))]
Cancel = Annotated[LocalUser, Depends(required(PERMISSIONS["cancel"]))]


class WorkcenterRequest(StrictRequest):
    code: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1, le=9_000_000_000_000_000_000)
    name: str = Field(min_length=1, max_length=160)
    effective_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_until: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class Operation(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    sequence: int = Field(ge=1, le=50)
    workcenter_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    minutes_per_batch: int = Field(ge=1, le=9_000_000_000_000_000_000)


class RoutingRequest(StrictRequest):
    number: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1, le=9_000_000_000_000_000_000)
    bom_version_id: str = Field(min_length=1, max_length=160)
    effective_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    effective_until: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    operations: list[Operation] = Field(min_length=1, max_length=50)


class CostClaim(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    effect_id: str = Field(min_length=1, max_length=160)
    line_id: str = Field(min_length=1, max_length=160)
    kind: Literal["Labor", "Overhead"]
    operation_sequence: int = Field(ge=1, le=50)
    minutes: int = Field(ge=1, le=9_000_000_000_000_000_000)
    rate_minor_per_hour: str = Field(pattern=r"^[1-9][0-9]{0,18}$")

    def claim_payload(self) -> dict[str, Any]:
        values = self.model_dump()
        values["rate_minor_per_hour"] = int(self.rate_minor_per_hour)
        return values


class ManufacturingOrderRequest(OrderRequest):
    routing_id: str = Field(min_length=1, max_length=160)
    claims: list[CostClaim] = Field(min_length=1, max_length=100)


class OperationReport(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    sequence: int = Field(ge=1, le=50)
    minutes: int = Field(ge=1, le=9_000_000_000_000_000_000)
    evidence_reference: str = Field(min_length=1, max_length=500)


class ProductionRequest(StrictRequest):
    output_quantity: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    operations: list[OperationReport] = Field(min_length=1, max_length=50)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class InspectionRequest(StrictRequest):
    accepted_quantity: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    rejected_quantity: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    inspection_reference: str = Field(min_length=1, max_length=500)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


def execute(request: Request, user: LocalUser,
            action: Callable[[ManufacturingExecutionV2Service, PostingActor, FinanceCoreExecutionScope], Any]) -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="manufacturing_execution_v2_backend_unavailable", message="Expense-backed inspected manufacturing requires PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        try:
            owner = ManufacturingExecutionV2Service(PostgresManufacturingExecutionV2Repository(finance.connection, scope.tenant_id))
            return project_v2(action(owner, actor, scope))
        except (FinancePostingError, InventoryReceiptPostingError) as exc:
            raise APIError(status_code=403 if "denied" in exc.code else 404 if "not_found" in exc.code else 409,
                code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="manufacturing_execution_v2_state_conflict", message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


def project_v2(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {name: project_v2(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [project_v2(item) for item in value]
    if type(value) is int and (key == "rate_minor_per_hour" or abs(value) > 9_007_199_254_740_991):
        return str(value)
    return project(value, key)


@router.get("/orders")
def list_sources(request: Request, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: owner.list_sources(scope_fields(scope), actor=actor))


@router.get("/orders/{identifier}")
def get_order(request: Request, identifier: str, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"order": owner.get_order(identifier, actor=actor)})


@router.post("/workcenters")
def create_workcenter(request: Request, payload: WorkcenterRequest, user: Create) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"definition": owner.create_workcenter(
        WorkcenterPreparation(**payload.model_dump(exclude={"command_id"}), scope=scope_fields(scope)), command_id=payload.command_id, actor=actor)})


@router.post("/routings")
def create_routing(request: Request, payload: RoutingRequest, user: Create) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"definition": owner.create_routing(
        RoutingPreparation(**payload.model_dump(exclude={"command_id"}), scope=scope_fields(scope)), command_id=payload.command_id, actor=actor)})


@router.post("/definitions/{identifier}/approve")
def approve_definition(request: Request, identifier: str, payload: PhaseRequest, user: Approve) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"definition": owner.approve_definition(identifier, **payload.model_dump(), actor=actor)})


@router.post("/orders")
def create_order(request: Request, payload: ManufacturingOrderRequest, user: Create) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"order": owner.create_order(ManufacturingOrderPreparation(
        material=OrderPreparation(**payload.model_dump(exclude={"command_id", "routing_id", "claims"}), **scope_fields(scope)),
        routing_id=payload.routing_id, claims=[claim.claim_payload() for claim in payload.claims]), command_id=payload.command_id, actor=actor)})


def phase(request: Request, user: LocalUser, identifier: str, kind: Literal["order", "production", "inspection"],
          operation: Literal["prepare", "review", "post", "cancel"], payload: PhaseRequest) -> dict[str, Any]:
    def invoke(owner: ManufacturingExecutionV2Service, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Any:
        method = {"order": owner.act_order, "production": owner.act_production, "inspection": owner.act_inspection}[kind]
        return {kind: method(identifier, operation, **payload.model_dump(), actor=actor)}
    return execute(request, user, invoke)


@router.post("/orders/{identifier}/prepare")
def prepare_order(request: Request, identifier: str, payload: PhaseRequest, user: Manage) -> dict[str, Any]:
    return phase(request, user, identifier, "order", "prepare", payload)


@router.post("/orders/{identifier}/review")
def review_order(request: Request, identifier: str, payload: PhaseRequest, user: Review) -> dict[str, Any]:
    return phase(request, user, identifier, "order", "review", payload)


@router.post("/orders/{identifier}/post")
def post_order(request: Request, identifier: str, payload: PhaseRequest, user: Post) -> dict[str, Any]:
    return phase(request, user, identifier, "order", "post", payload)


@router.post("/orders/{identifier}/cancel")
def cancel_order(request: Request, identifier: str, payload: PhaseRequest, user: Cancel) -> dict[str, Any]:
    return phase(request, user, identifier, "order", "cancel", payload)


@router.post("/orders/{identifier}/productions")
def produce(request: Request, identifier: str, payload: ProductionRequest, user: Manage) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"production": owner.produce(identifier, **payload.model_dump(), actor=actor)})


@router.post("/productions/{identifier}/review")
def review_production(request: Request, identifier: str, payload: PhaseRequest, user: Review) -> dict[str, Any]:
    return phase(request, user, identifier, "production", "review", payload)


@router.post("/productions/{identifier}/post")
def post_production(request: Request, identifier: str, payload: PhaseRequest, user: Post) -> dict[str, Any]:
    return phase(request, user, identifier, "production", "post", payload)


@router.post("/productions/{identifier}/cancel")
def cancel_production(request: Request, identifier: str, payload: PhaseRequest, user: Cancel) -> dict[str, Any]:
    return phase(request, user, identifier, "production", "cancel", payload)


@router.post("/productions/{identifier}/inspections")
def inspect_production(request: Request, identifier: str, payload: InspectionRequest, user: Manage) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"inspection": owner.inspect(identifier, **payload.model_dump(), actor=actor)})


@router.post("/inspections/{identifier}/review")
def review_inspection(request: Request, identifier: str, payload: PhaseRequest, user: Review) -> dict[str, Any]:
    return phase(request, user, identifier, "inspection", "review", payload)


@router.post("/inspections/{identifier}/post")
def post_inspection(request: Request, identifier: str, payload: PhaseRequest, user: Post) -> dict[str, Any]:
    return phase(request, user, identifier, "inspection", "post", payload)


@router.post("/inspections/{identifier}/cancel")
def cancel_inspection(request: Request, identifier: str, payload: PhaseRequest, user: Cancel) -> dict[str, Any]:
    return phase(request, user, identifier, "inspection", "cancel", payload)
