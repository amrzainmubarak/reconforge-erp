"""Strict scoped fixed asset lifecycle; every monetary value is exact text."""

from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.operational_finance import _authority
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.fixed_assets import AssetAcquisition
from reconforge.infrastructure.postgres_fixed_assets import PostgresFixedAssetsRepository
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/fixed-assets", tags=["fixed-assets"])
Read = Annotated[LocalUser, Depends(require_permission("finance_core.read"))]
Manage = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]
Review = Annotated[LocalUser, Depends(require_permission("finance_core.validate"))]
Post = Annotated[LocalUser, Depends(require_permission("finance_core.post"))]


class AcquisitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    asset_number: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    journal_code: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    in_service_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    cost_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    salvage_minor: str = Field(pattern=r"^(0|[1-9][0-9]{0,18})$")
    useful_life_months: int = Field(ge=1, le=1200)
    asset_account_code: str = Field(min_length=1, max_length=64)
    accumulated_account_code: str = Field(min_length=1, max_length=64)
    expense_account_code: str = Field(min_length=1, max_length=64)
    cash_account_code: str = Field(min_length=1, max_length=64)
    gain_account_code: str = Field(min_length=1, max_length=64)
    loss_account_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=500)


class OperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    kind: Literal["depreciate", "dispose"]
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    through_month: str = Field(default="", pattern=r"^([0-9]{4}-(0[1-9]|1[0-2]))?$")
    proceeds_minor: str = Field(default="0", pattern=r"^(0|[1-9][0-9]{0,18})$")
    reason: str = Field(min_length=1, max_length=500)


class PhaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    expected_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


def project(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {field: project(item, field) for field, item in value.items()}
    if isinstance(value, list):
        return [project(item) for item in value]
    return str(value) if type(value) is int and key.endswith("_minor") else value


def execute(request: Request, user: LocalUser,
            operation: Callable[[PostgresFixedAssetsRepository, PostingActor, FinanceCoreExecutionScope], Any]) -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="asset_backend_unavailable", message="Fixed asset posting requires PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        try:
            return project(operation(PostgresFixedAssetsRepository(finance.connection, scope.tenant_id), actor, scope))
        except FinancePostingError as exc:
            status = (403 if "denied" in exc.code else 404 if "not_found" in exc.code
                      else 409 if any(word in exc.code for word in ("conflict", "state_invalid", "review_invalid")) else 400)
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="asset_state_conflict", message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.post("/assets")
def acquire(request: Request, payload: AcquisitionRequest, user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.manage")

    def run(repository: PostgresFixedAssetsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Any:
        args = payload.model_dump(exclude={"command_id", "cost_minor", "salvage_minor"})
        result = repository.acquire(AssetAcquisition(**args, cost_minor=int(payload.cost_minor), salvage_minor=int(payload.salvage_minor),
            workspace_id=scope.workspace_id, organization_id=str(scope.organization_id), legal_entity_id=str(scope.legal_entity_id),
            organization_code=scope.organization_code, entity_code=scope.entity_code), command_id=payload.command_id, actor=actor)
        _authority(request, "finance_core.manage", result, audit=False)
        return {"plan": result}

    return execute(request, user, run)


@router.get("/assets")
def list_assets(request: Request, user: Read, after: str = Query(default="", max_length=160), limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    _authority(request, "finance_core.read")
    return execute(request, user, lambda repository, actor, scope: repository.list_assets(
        {"workspace_id": scope.workspace_id, "organization_id": scope.organization_id, "legal_entity_id": scope.legal_entity_id},
        actor=actor, after=after, limit=limit))


@router.get("/assets/{asset_id}")
def get_asset(request: Request, asset_id: str, user: Read, before_sequence: int | None = Query(default=None, ge=1, le=1202)) -> dict[str, Any]:
    _authority(request, "finance_core.read")
    return execute(request, user, lambda repository, actor, scope: {"asset": repository.get(asset_id, actor=actor, before_sequence=before_sequence)})


@router.get("/plans/{plan_id}")
def get_plan(request: Request, plan_id: str, user: Read) -> dict[str, Any]:
    _authority(request, "finance_core.read")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.get_plan(plan_id, actor=actor)})


@router.post("/assets/{asset_id}/operations")
def prepare(request: Request, asset_id: str, payload: OperationRequest, user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.manage")

    def run(repository: PostgresFixedAssetsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Any:
        return {"plan": repository.prepare(asset_id, **payload.model_dump(exclude={"proceeds_minor"}), proceeds_minor=int(payload.proceeds_minor), actor=actor)}

    return execute(request, user, run)


@router.get("/plans/{plan_id}/evidence")
def get_plan_evidence(request: Request, plan_id: str, user: Read) -> dict[str, Any]:
    _authority(request, "finance_core.read")
    return execute(request, user, lambda repository, actor, scope: {"evidence": repository.plan_evidence(plan_id, actor=actor)})


@router.post("/plans/{plan_id}/review")
def review(request: Request, plan_id: str, payload: PhaseRequest, user: Review) -> dict[str, Any]:
    _authority(request, "finance_core.validate")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.review(plan_id, **payload.model_dump(), actor=actor)})


@router.post("/plans/{plan_id}/post")
def post(request: Request, plan_id: str, payload: PhaseRequest, user: Post) -> dict[str, Any]:
    _authority(request, "finance_core.post")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.post(plan_id, **payload.model_dump(), actor=actor)})
