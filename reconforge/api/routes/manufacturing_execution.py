"""Scoped real BOM, material issue and finished output commands."""
from collections.abc import Callable
from typing import Annotated, Any, Literal, TypedDict

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
from reconforge.application.manufacturing_execution import ManufacturingExecutionService
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.manufacturing_execution import PERMISSIONS, READ, BomPreparation, OrderPreparation
from reconforge.infrastructure.postgres_manufacturing_execution import PostgresManufacturingExecutionRepository
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/manufacturing-execution", tags=["manufacturing-execution"])
Read = Annotated[LocalUser, Depends(required(READ))]
Create = Annotated[LocalUser, Depends(required(PERMISSIONS["create"]))]
Manage = Annotated[LocalUser, Depends(required(PERMISSIONS["prepare"]))]
BomReview = Annotated[LocalUser, Depends(required(PERMISSIONS["approve-bom"]))]
Review = Annotated[LocalUser, Depends(required(PERMISSIONS["review"]))]
Post = Annotated[LocalUser, Depends(required(PERMISSIONS["post"]))]
Cancel = Annotated[LocalUser, Depends(required(PERMISSIONS["cancel"]))]


class StrictRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    command_id: str = Field(min_length=1, max_length=140)
    reason: str = Field(min_length=1, max_length=500)


class Component(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    item_code: str = Field(min_length=1, max_length=64)
    quantity: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")


class BomRequest(StrictRequest):
    number: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1, le=9_000_000_000_000_000_000)
    output_item_code: str = Field(min_length=1, max_length=64)
    output_quantity: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    components: list[Component] = Field(min_length=1, max_length=100)


class OrderRequest(StrictRequest):
    number: str = Field(min_length=1, max_length=64)
    bom_version_id: str = Field(min_length=1, max_length=160)
    output_quantity: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    component_location_code: str = Field(min_length=1, max_length=130)
    finished_location_code: str = Field(min_length=1, max_length=130)
    component_policy_code: str = Field(min_length=1, max_length=64)
    finished_policy_code: str = Field(min_length=1, max_length=64)
    journal_code: str = Field(min_length=1, max_length=64)
    wip_account_code: str = Field(min_length=1, max_length=64)
    scrap_account_code: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class PhaseRequest(StrictRequest):
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class CompletionRequest(StrictRequest):
    good_quantity: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    scrap_quantity: str = Field(pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


def project(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {name: project(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [project(item) for item in value]
    return str(value) if type(value) is int and (key.endswith("_minor") or key.endswith("_scaled")) else value


def execute(request: Request, user: LocalUser,
            action: Callable[[ManufacturingExecutionService, PostingActor, FinanceCoreExecutionScope], Any]) -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="manufacturing_execution_backend_unavailable", message="Native manufacturing requires PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        try:
            return project(action(ManufacturingExecutionService(PostgresManufacturingExecutionRepository(finance.connection, scope.tenant_id)), actor, scope))
        except FinancePostingError as exc:
            raise APIError(status_code=403 if "denied" in exc.code else 404 if "not_found" in exc.code else 409,
                           code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="manufacturing_execution_state_conflict", message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


class ManufacturingScope(TypedDict):
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str


def scope_fields(scope: FinanceCoreExecutionScope) -> ManufacturingScope:
    return {"workspace_id": scope.workspace_id, "organization_id": str(scope.organization_id), "legal_entity_id": str(scope.legal_entity_id),
            "organization_code": scope.organization_code, "entity_code": scope.entity_code}


@router.get("/orders")
def list_orders(request: Request, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: owner.list_orders(scope_fields(scope), actor=actor))


@router.post("/boms")
def prepare_bom(request: Request, payload: BomRequest, user: Create) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"bom": owner.prepare_bom(BomPreparation(
        **payload.model_dump(exclude={"command_id"}), **scope_fields(scope)), command_id=payload.command_id, actor=actor)})


@router.post("/boms/{bom_id}/approve")
def approve_bom(request: Request, bom_id: str, payload: PhaseRequest, user: BomReview) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"bom": owner.approve_bom(bom_id, **payload.model_dump(), actor=actor)})


@router.post("/orders")
def create_order(request: Request, payload: OrderRequest, user: Create) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"order": owner.create_order(OrderPreparation(
        **payload.model_dump(exclude={"command_id"}), **scope_fields(scope)), command_id=payload.command_id, actor=actor)})


@router.get("/orders/{order_id}")
def get_order(request: Request, order_id: str, user: Read) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"order": owner.get_order(order_id, actor=actor)})


@router.get("/orders/{order_id}/requirements")
def requirements(request: Request, order_id: str, user: Read) -> dict[str, Any]:
    def run(owner: ManufacturingExecutionService, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Any:
        order = owner.get_order(order_id, actor=actor)
        return {"requirements": [owner.get_requirement(line["requirement_id"], actor=actor) for line in order["requirements"]]}
    return execute(request, user, run)


def order_phase(request: Request, user: LocalUser, identifier: str, operation: Literal["prepare", "review", "post", "cancel"], payload: PhaseRequest) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"order": owner.act(identifier, operation, **payload.model_dump(), actor=actor)})


@router.post("/orders/{order_id}/prepare")
def prepare_issue(request: Request, order_id: str, payload: PhaseRequest, user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.manage")
    return order_phase(request, user, order_id, "prepare", payload)


@router.post("/orders/{order_id}/review")
def review_issue(request: Request, order_id: str, payload: PhaseRequest, user: Review) -> dict[str, Any]:
    return order_phase(request, user, order_id, "review", payload)


@router.post("/orders/{order_id}/post")
def post_issue(request: Request, order_id: str, payload: PhaseRequest, user: Post) -> dict[str, Any]:
    return order_phase(request, user, order_id, "post", payload)


@router.post("/orders/{order_id}/cancel")
def cancel_order(request: Request, order_id: str, payload: PhaseRequest, user: Cancel) -> dict[str, Any]:
    return order_phase(request, user, order_id, "cancel", payload)


@router.post("/orders/{order_id}/completions")
def prepare_completion(request: Request, order_id: str, payload: CompletionRequest, user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.manage")
    return execute(request, user, lambda owner, actor, scope: {"completion": owner.prepare_completion(order_id, **payload.model_dump(), actor=actor)})


def completion_phase(request: Request, user: LocalUser, identifier: str, operation: Literal["review", "post", "cancel"], payload: PhaseRequest) -> dict[str, Any]:
    return execute(request, user, lambda owner, actor, scope: {"completion": owner.act_completion(identifier, operation, **payload.model_dump(), actor=actor)})


@router.post("/completions/{completion_id}/review")
def review_completion(request: Request, completion_id: str, payload: PhaseRequest, user: Review) -> dict[str, Any]:
    return completion_phase(request, user, completion_id, "review", payload)


@router.post("/completions/{completion_id}/post")
def post_completion(request: Request, completion_id: str, payload: PhaseRequest, user: Post) -> dict[str, Any]:
    return completion_phase(request, user, completion_id, "post", payload)


@router.post("/completions/{completion_id}/cancel")
def cancel_completion(request: Request, completion_id: str, payload: PhaseRequest, user: Cancel) -> dict[str, Any]:
    return completion_phase(request, user, completion_id, "cancel", payload)
