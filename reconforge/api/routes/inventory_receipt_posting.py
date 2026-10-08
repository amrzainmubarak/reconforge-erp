"""Authenticated complete source commands over the existing receipt/FIFO/GL owner."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import Decimal
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import (
    enforce_server_scoped_permission,
    get_auth_db,
    get_current_user,
    require_permission,
)
from reconforge.api.errors import APIError
from reconforge.api.inventory_receipt_contract import project_receipt_view
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.api.server_identity import request_execution_scope
from reconforge.application.inventory_receipt_posting import InventoryReceiptPostingApplicationService
from reconforge.auth.models import LocalUser
from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext
from reconforge.auth.webauthn_config import WebAuthnRuntime
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.inventory_receipt_posting import (
    COMMIT_PERMISSIONS,
    PREPARE_PERMISSIONS,
    READ_PERMISSIONS,
    REVIEW_PERMISSIONS,
    ReceiptPreparation,
    ReceiptReversalPreparation,
)
from reconforge.infrastructure.postgres_inventory_receipt_posting import PostgresInventoryReceiptPostingRepository
from reconforge.platform.common import ServerPrincipal, current_server_principal

router = APIRouter(prefix="/inventory-receipt-posting", tags=["inventory-receipt-posting"])
REVERSE_PERMISSIONS = PREPARE_PERMISSIONS | frozenset({"inventory.valuation.reverse.manage", "finance_core.reverse"})

def _required(permissions: frozenset[str]) -> Callable[..., LocalUser]:
    def dependency(request: Request, user: LocalUser = Depends(get_current_user), connection: sqlite3.Connection | None = Depends(get_auth_db)) -> LocalUser:
        for permission in sorted(permissions):
            require_permission(permission)(request, user, connection)
        return user
    metadata = cast(Any, dependency)
    metadata.__reconforge_permissions__ = permissions
    metadata.__reconforge_permission_mode__ = "all"
    return dependency

Prepare = Annotated[LocalUser, Depends(_required(PREPARE_PERMISSIONS | READ_PERMISSIONS))]
Review = Annotated[LocalUser, Depends(_required(REVIEW_PERMISSIONS | READ_PERMISSIONS))]
Commit = Annotated[LocalUser, Depends(_required(COMMIT_PERMISSIONS | READ_PERMISSIONS))]
Read = Annotated[LocalUser, Depends(_required(READ_PERMISSIONS))]
Reverse = Annotated[LocalUser, Depends(_required(REVERSE_PERMISSIONS | READ_PERMISSIONS))]

class ReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=160)
    receipt_number: str = Field(min_length=1, max_length=64)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_id: str = Field(min_length=1, max_length=160)
    item_code: str = Field(min_length=1, max_length=64)
    location_code: str = Field(min_length=1, max_length=129)
    quantity: str = Field(min_length=1, max_length=64)
    total_value_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    policy_code: str = Field(min_length=1, max_length=64)
    organization_code: str = Field(min_length=1, max_length=64)
    entity_code: str = Field(min_length=1, max_length=64)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=500)

class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=160)
    expected_plan_digest: str = Field(pattern="^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)

class CommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=160)
    expected_review_digest: str = Field(pattern="^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)

class ReversalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=160)
    reversal_number: str = Field(min_length=1, max_length=64)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=500)

def _authority(request: Request, permissions: frozenset[str], plan: Mapping[str, Any] | None = None, *, audit: bool = True) -> None:
    scope = request_execution_scope(request)
    organization, entity = scope.organization_id, scope.legal_entity_id
    amount = None
    if plan is not None:
        bound = plan["scope"]
        if bound["workspace_id"] != scope.workspace_id or (organization and bound["organization_id"] != organization) or (entity and bound["legal_entity_id"] != entity):
            raise APIError(status_code=403, code="inventory_receipt_scope_denied", message="Receipt is outside the authorized request scope.")
        organization, entity = bound["organization_id"], bound["legal_entity_id"]
        units, precision = plan["source"]["total_value_minor"], plan["currency_policy"]["currency_precision"]
        # Build exact decimal text; ambient Decimal precision must not round large values.
        factor = 10 ** precision
        amount = Decimal(str(units) if precision == 0 else f"{units // factor}.{units % factor:0{precision}d}")
    for permission in sorted(permissions):
        if audit:
            enforce_server_scoped_permission(request, permission=permission, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id, organization_id=organization, entity_id=entity, amount=amount)
        else:
            # The source owner holds the audit chain lock until commit. Reusing a
            # second connection for authorization evidence here would self-block.
            # Evaluate the already current principal before returning; denial rolls
            # back the complete outer owner, including all business evidence.
            principal = current_server_principal()
            if principal is None:
                raise APIError(status_code=401, code="auth_required", message="Authentication required.")
            context = PolicyEvaluationContext(
                user_id=principal.user.id, username=principal.user.username, user_permissions=principal.permissions,
                principal_type=principal.principal_type, step_up_active=principal.step_up_active, step_up_enforced=True,
                required_step_up_method="webauthn_user_verified" if isinstance(getattr(request.app.state, "webauthn_runtime", None), WebAuthnRuntime) else None,
                step_up_method=principal.step_up_method, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id,
                organization_id=organization, entity_id=entity, amount=amount,
                authorized_tenant_ids=principal.authorized_tenant_ids or frozenset({scope.tenant_id}),
                authorized_workspace_ids=principal.authorized_workspace_ids,
                authorized_organization_ids=principal.authorized_organization_ids,
                authorized_entity_ids=principal.authorized_legal_entity_ids,
            )
            if not CentralPolicyEngine().evaluate(context, required_permission=permission).allowed:
                raise APIError(status_code=403, code="inventory_receipt_scope_denied", message="Receipt amount or hierarchy is outside current authority.")

def _execute(request: Request, user: LocalUser, permissions: frozenset[str], operation: Callable[[InventoryReceiptPostingApplicationService, PostingActor, FinanceCoreExecutionScope], Mapping[str, Any]], *, organization_code: str = "", entity_code: str = "") -> dict[str, Any]:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="inventory_receipt_backend_unavailable", message="Receipt posting requires the configured PostgreSQL server profile.")
    principal = getattr(request.state, "server_principal", None) or current_server_principal()
    if not isinstance(principal, ServerPrincipal) or principal.user.id != user.id:
        raise APIError(status_code=503, code="inventory_receipt_identity_unavailable", message="Receipt posting requires verified server identity.")
    actor = PostingActor(user.id, user.username, principal.permissions, principal.principal_type, principal.step_up_active)
    _authority(request, permissions)
    def invoke(repository: Any, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        try:
            service = InventoryReceiptPostingApplicationService(PostgresInventoryReceiptPostingRepository(repository.connection, scope.tenant_id, strict_command_actor=True))
            view = operation(service, actor, scope)
            _authority(request, permissions, view["plan"], audit=False)
            return {"receipt": project_receipt_view(view)}
        except APIError:
            raise
        except FinancePostingError as exc:
            status = 403 if any(word in exc.code for word in ("denied", "required")) else 409 if any(word in exc.code for word in ("conflict", "not_unused")) else 400
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise APIError(status_code=503, code="inventory_receipt_response_invalid", message="Receipt evidence could not be verified.") from exc
    return execute_postgres_finance_core_scoped(request, invoke, organization_code=organization_code, entity_code=entity_code)

@router.post("/plans")
def prepare(request: Request, payload: ReceiptRequest, user: Prepare) -> dict[str, Any]:
    scope = request_execution_scope(request)
    if payload.workspace not in {"default", scope.workspace_id}:
        raise APIError(status_code=403, code="workspace_scope_denied", message="Receipt workspace is outside the authorized scope.")
    def run(service: InventoryReceiptPostingApplicationService, actor: PostingActor, bound: FinanceCoreExecutionScope) -> Mapping[str, Any]:
        fields = payload.model_dump(exclude={"command_id"})
        fields["total_value_minor"] = int(payload.total_value_minor)
        prepared = replace(ReceiptPreparation(**fields), workspace=bound.workspace_id, organization_code=bound.organization_code, entity_code=bound.entity_code)
        plan = service.prepare_receipt(prepared, command_id=payload.command_id, actor=actor)
        _authority(request, PREPARE_PERMISSIONS, plan, audit=False)
        return service.get_plan(plan["plan_id"], actor=actor)
    return _execute(request, user, PREPARE_PERMISSIONS, run, organization_code=payload.organization_code, entity_code=payload.entity_code)

@router.get("/plans/{plan_id}")
def get_plan(request: Request, plan_id: str, user: Read) -> dict[str, Any]:
    return _execute(request, user, READ_PERMISSIONS, lambda service, actor, scope: service.get_plan(plan_id, actor=actor))

@router.post("/plans/{plan_id}/review")
def review(request: Request, plan_id: str, payload: ReviewRequest, user: Review) -> dict[str, Any]:
    def run(service: InventoryReceiptPostingApplicationService, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Mapping[str, Any]:
        view = service.get_plan(plan_id, actor=actor)
        _authority(request, REVIEW_PERMISSIONS | (frozenset({"inventory.valuation.reverse.approve", "finance_core.reverse"}) if view["plan"]["operation"] == "FullReceiptReversal" else frozenset()), view["plan"])
        result = service.review(plan_id, **payload.model_dump(), actor=actor)
        return {**view, "review": result}
    return _execute(request, user, REVIEW_PERMISSIONS, run)

@router.post("/plans/{plan_id}/commit")
def commit(request: Request, plan_id: str, payload: CommitRequest, user: Commit) -> dict[str, Any]:
    def run(service: InventoryReceiptPostingApplicationService, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Mapping[str, Any]:
        view = service.get_plan(plan_id, actor=actor)
        _authority(request, COMMIT_PERMISSIONS | (frozenset({"inventory.valuation.reverse.approve", "finance_core.reverse"}) if view["plan"]["operation"] == "FullReceiptReversal" else frozenset()), view["plan"])
        effect = service.commit(plan_id, **payload.model_dump(), actor=actor)
        return {**view, "effect": effect}
    return _execute(request, user, COMMIT_PERMISSIONS, run)

@router.post("/plans/{plan_id}/reversal")
def prepare_reversal(request: Request, plan_id: str, payload: ReversalRequest, user: Reverse) -> dict[str, Any]:
    def run(service: InventoryReceiptPostingApplicationService, actor: PostingActor, scope: FinanceCoreExecutionScope) -> Mapping[str, Any]:
        view = service.get_plan(plan_id, actor=actor)
        _authority(request, REVERSE_PERMISSIONS, view["plan"])
        fields = payload.model_dump(exclude={"command_id"})
        plan = service.prepare_reversal(ReceiptReversalPreparation(original_plan_id=plan_id, **fields), command_id=payload.command_id, actor=actor)
        return service.get_plan(plan["plan_id"], actor=actor)
    return _execute(request, user, REVERSE_PERMISSIONS, run)
