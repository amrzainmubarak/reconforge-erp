"""PostgreSQL operational source plans, independent review and accrual posting."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import enforce_server_scoped_permissions, require_permission
from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor, _error
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.api.server_identity import request_execution_scope
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor, canonical_json
from reconforge.domain.operational_finance import SOURCE_PERMISSIONS, OperationalFinancePreparation, exact_minor_text
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository

router = APIRouter(prefix="/operational-finance", tags=["operational-finance"])
Read = Annotated[LocalUser, Depends(require_permission("finance_core.read"))]
Manage = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]
Review = Annotated[LocalUser, Depends(require_permission("finance_core.validate"))]
Post = Annotated[LocalUser, Depends(require_permission("finance_core.post"))]


class PreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    source_kind: Literal["ARInvoice", "ARReceipt", "APInvoice", "APPayment"]
    source_id: str = Field(min_length=1, max_length=160)
    journal_code: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    debit_account_code: str = Field(min_length=1, max_length=64)
    credit_account_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=500)


class PhaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    expected_plan_digest: str = Field(pattern="^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


def project_plan(value: dict[str, Any]) -> dict[str, Any]:
    """No financial minor units cross the JS boundary as floating numbers."""
    fields = (
        "id",
        "entry_id",
        "source_kind",
        "source_id",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "organization_code",
        "entity_code",
        "period_id",
        "posting_date",
        "currency_code",
        "currency_precision",
        "preparer_actor_id",
        "reviewer_actor_id",
        "plan_digest",
        "validation_digest",
        "review_digest",
        "posting_effect_id",
        "source_effect_id",
        "status",
        "reason",
    )
    return {
        "api_contract_version": "operational-finance-api-v1",
        **{key: value[key] for key in fields},
        "amount_minor": str(value["amount_minor"]),
        "lines": [
            {
                "account_id": line["account_id"],
                "debit_minor": str(line["debit_minor"]),
                "credit_minor": str(line["credit_minor"]),
            }
            for line in value["snapshot"]["lines"]
        ],
        "source_json": canonical_json(value["source_snapshot"]),
        "snapshot_json": canonical_json(value["snapshot"]),
    }


def _authority(request: Request, permission: str, plan: dict[str, Any] | None = None, *, source: bool = False) -> None:
    scope = request_execution_scope(request)
    if not scope.organization_id or not scope.legal_entity_id:
        raise APIError(
            status_code=403, code="operational_scope_required", message="Select an organization and legal entity."
        )
    permissions = (
        frozenset({permission, SOURCE_PERMISSIONS[plan["source_kind"]]}) if source and plan else frozenset({permission})
    )
    amount = None if plan is None else Decimal(exact_minor_text(plan["amount_minor"], plan["currency_precision"]))
    if plan is not None and any(
        plan[key] != expected
        for key, expected in (
            ("workspace_id", scope.workspace_id),
            ("organization_id", scope.organization_id),
            ("legal_entity_id", scope.legal_entity_id),
        )
    ):
        raise APIError(
            status_code=403, code="operational_scope_denied", message="Source plan is outside selected authority."
        )
    enforce_server_scoped_permissions(
        request,
        permissions=permissions,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        organization_id=scope.organization_id,
        entity_id=scope.legal_entity_id,
        amount=amount,
    )


def _execute(
    request: Request,
    user: LocalUser,
    operation: Callable[
        [PostgresOperationalFinanceRepository, PostingActor, FinanceCoreExecutionScope], dict[str, Any]
    ],
) -> dict[str, Any]:
    if not server_finance_core_enabled(request):
        raise APIError(
            status_code=503,
            code="operational_backend_unavailable",
            message="Operational source posting requires the PostgreSQL profile.",
        )
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        try:
            return operation(PostgresOperationalFinanceRepository(finance.connection, scope.tenant_id), actor, scope)
        except FinancePostingError as exc:
            if exc.code.endswith("not_found"):
                status = 404
            elif exc.code.endswith("denied"):
                status = 403
            elif exc.code in {
                "operational_state_conflict",
                "operational_command_conflict",
                "operational_review_invalid",
                "operational_source_changed",
                "operational_source_state_invalid",
            }:
                status = 409
            else:
                raise _error(exc) from exc
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.get("/plans")
def list_plans(request: Request, current_user: Read, limit: Annotated[int, Query(ge=1, le=100)] = 50) -> dict[str, Any]:
    _authority(request, "finance_core.read")

    def run(
        repository: PostgresOperationalFinanceRepository, actor: PostingActor, scope: FinanceCoreExecutionScope
    ) -> dict[str, Any]:
        return {
            "plans": [
                project_plan(plan)
                for plan in repository.list(
                    workspace_id=scope.workspace_id,
                    organization_id=str(scope.organization_id),
                    legal_entity_id=str(scope.legal_entity_id),
                    actor=actor,
                    limit=limit,
                )
            ]
        }

    return _execute(request, current_user, run)


@router.get("/plans/{plan_id}")
def get_plan(request: Request, plan_id: str, current_user: Read) -> dict[str, Any]:
    _authority(request, "finance_core.read")

    def run(
        repository: PostgresOperationalFinanceRepository, actor: PostingActor, scope: FinanceCoreExecutionScope
    ) -> dict[str, Any]:
        value = repository.get(plan_id, actor=actor)
        _authority(request, "finance_core.read", value)
        return {"plan": project_plan(value)}

    return _execute(request, current_user, run)


@router.post("/plans")
def prepare(request: Request, payload: PreparationRequest, current_user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.manage")

    def run(
        repository: PostgresOperationalFinanceRepository, actor: PostingActor, scope: FinanceCoreExecutionScope
    ) -> dict[str, Any]:
        value = repository.prepare(
            OperationalFinancePreparation(
                workspace_id=scope.workspace_id,
                organization_id=str(scope.organization_id),
                legal_entity_id=str(scope.legal_entity_id),
                organization_code=scope.organization_code,
                entity_code=scope.entity_code,
                **payload.model_dump(exclude={"command_id"}),
            ),
            command_id=payload.command_id,
            actor=actor,
        )
        _authority(request, "finance_core.manage", value)
        return {"plan": project_plan(value)}

    return _execute(request, current_user, run)


@router.post("/plans/{plan_id}/review")
def review(request: Request, plan_id: str, payload: PhaseRequest, current_user: Review) -> dict[str, Any]:
    _authority(request, "finance_core.validate")

    def run(
        repository: PostgresOperationalFinanceRepository, actor: PostingActor, scope: FinanceCoreExecutionScope
    ) -> dict[str, Any]:
        value = repository.get(plan_id, actor=actor)
        _authority(request, "finance_core.validate", value)
        return {"plan": project_plan(repository.review(plan_id, **payload.model_dump(), actor=actor))}

    return _execute(request, current_user, run)


@router.post("/plans/{plan_id}/post")
def post(request: Request, plan_id: str, payload: PhaseRequest, current_user: Post) -> dict[str, Any]:
    _authority(request, "finance_core.post")

    def run(
        repository: PostgresOperationalFinanceRepository, actor: PostingActor, scope: FinanceCoreExecutionScope
    ) -> dict[str, Any]:
        value = repository.get(plan_id, actor=actor)
        _authority(request, "finance_core.post", value, source=True)
        if value["source_kind"] in {"ARReceipt", "APPayment"}:
            raise APIError(
                status_code=409,
                code="operational_owner_required",
                message="Use the Sales collection or Procurement settlement command to commit all source effects together.",
            )
        return {"plan": project_plan(repository.post(plan_id, **payload.model_dump(), actor=actor))}

    return _execute(request, current_user, run)
