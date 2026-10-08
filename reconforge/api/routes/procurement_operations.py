"""Real stock procurement operations on the configured PostgreSQL owner."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import replace
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
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.procurement_operations import READ, ProcurementPreparation
from reconforge.infrastructure.postgres_procurement_operations import (
    OPERATIONS,
    PERMISSIONS,
    PostgresProcurementOperationsRepository,
)
from reconforge.platform.common import PlatformError, ServerPrincipal, current_server_principal

router = APIRouter(prefix="/procurement-operations", tags=["procurement-operations"])


def required(permissions: frozenset[str]) -> Callable[..., LocalUser]:
    def dependency(request: Request, user: LocalUser = Depends(get_current_user),
                   connection: sqlite3.Connection | None = Depends(get_auth_db)) -> LocalUser:
        for permission in sorted(permissions):
            require_permission(permission)(request, user, connection)
        return user
    cast(Any, dependency).__reconforge_permissions__ = permissions
    cast(Any, dependency).__reconforge_permission_mode__ = "all"
    return dependency


Read = Annotated[LocalUser, Depends(required(READ))]
Manage = Annotated[LocalUser, Depends(required(READ | PERMISSIONS["create"]))]
class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=160)
    number: str = Field(min_length=1, max_length=60)
    supplier_code: str = Field(min_length=1, max_length=64)
    item_code: str = Field(min_length=1, max_length=64)
    quantity: str = Field(min_length=1, max_length=64)
    unit_price_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    currency_code: str = Field(pattern="^[A-Z]{3}$")
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_id: str = Field(min_length=1, max_length=160)
    location_code: str = Field(min_length=1, max_length=129)
    policy_code: str = Field(min_length=1, max_length=64)
    journal_code: str = Field(min_length=1, max_length=64)
    ap_account_code: str = Field(min_length=1, max_length=64)
    cash_account_code: str = Field(min_length=1, max_length=64)
    organization_code: str = Field(min_length=1, max_length=64)
    entity_code: str = Field(min_length=1, max_length=64)
    workspace: str = Field(default="default", min_length=1, max_length=160)


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=160)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


def execute(request: Request, user: LocalUser, permissions: frozenset[str],
            operation: Callable[[PostgresProcurementOperationsRepository, PostingActor, FinanceCoreExecutionScope], Any],
            *, organization_code: str = "", entity_code: str = "") -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="procurement_backend_unavailable", message="Procurement operations require configured PostgreSQL.")
    principal = getattr(request.state, "server_principal", None) or current_server_principal()
    if not isinstance(principal, ServerPrincipal) or principal.user.id != user.id:
        raise APIError(status_code=401, code="procurement_identity_required", message="Verified server identity is required.")
    scope = request_execution_scope(request)
    for permission in sorted(permissions):
        enforce_server_scoped_permission(request, permission=permission, tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id, organization_id=scope.organization_id, entity_id=scope.legal_entity_id)
    actor = PostingActor(user.id, user.username, principal.permissions, principal.principal_type, principal.step_up_active)
    def invoke(repository: Any, bound: FinanceCoreExecutionScope) -> Any:
        try:
            value = operation(PostgresProcurementOperationsRepository(repository.connection, bound.tenant_id), actor, bound)
            if isinstance(value, dict) and value.get("receipt") is not None:
                value["receipt"] = project_receipt_view(value["receipt"])
            return value
        except FinancePostingError as exc:
            status = 403 if "denied" in exc.code or "required" in exc.code else 404 if "not_found" in exc.code else 409 if "conflict" in exc.code else 400
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="procurement_state_conflict", message=str(exc)) from exc
    return execute_postgres_finance_core_scoped(request, invoke, organization_code=organization_code, entity_code=entity_code)


@router.post("/cycles")
def create(request: Request, payload: CreateRequest, user: Manage) -> dict[str, Any]:
    scope = request_execution_scope(request)
    if payload.workspace not in {"default", scope.workspace_id}:
        raise APIError(status_code=403, code="workspace_scope_denied", message="Workspace is outside current authority.")
    def run(repository: PostgresProcurementOperationsRepository, actor: PostingActor, bound: FinanceCoreExecutionScope) -> dict[str, Any]:
        fields = payload.model_dump(exclude={"command_id"})
        fields["unit_price_minor"] = int(payload.unit_price_minor)
        prepared = replace(ProcurementPreparation(**fields), workspace=bound.workspace_id,
            organization_code=bound.organization_code, entity_code=bound.entity_code)
        return repository.create(prepared, command_id=payload.command_id, actor=actor)
    return execute(request, user, READ | PERMISSIONS["create"], run,
        organization_code=payload.organization_code, entity_code=payload.entity_code)


@router.get("/cycles")
def list_cycles(request: Request, user: Read) -> dict[str, Any]:
    return execute(request, user, READ, lambda repository, actor, scope: {"records": repository.list_cycles(scope.workspace_id, actor=actor)})


@router.get("/cycles/{cycle_id}")
def get_cycle(request: Request, cycle_id: str, user: Read) -> dict[str, Any]:
    return execute(request, user, READ, lambda repository, actor, scope: repository.get(cycle_id, actor=actor))


@router.get("/options")
def options(request: Request, user: Read) -> dict[str, Any]:
    return execute(request, user, READ, lambda repository, actor, scope:
        repository.options(scope.workspace_id, scope.organization_code, scope.entity_code, actor=actor))


@router.get("/scopes")
def scopes(request: Request, user: Read) -> dict[str, Any]:
    return execute(request, user, READ, lambda repository, actor, scope:
        {"records": repository.scopes(scope.workspace_id, actor=actor)})


def command_endpoint(operation: str) -> Callable[..., dict[str, Any]]:
    permissions = READ | PERMISSIONS[operation]
    def endpoint(request: Request, cycle_id: str, payload: CommandRequest,
                 user: LocalUser = Depends(required(permissions))) -> dict[str, Any]:
        return execute(request, user, permissions, lambda repository, actor, scope:
            repository.act(cycle_id, operation, **payload.model_dump(), actor=actor))
    endpoint.__name__ = "procurement_" + operation.replace("-", "_")
    return endpoint


for action in OPERATIONS:
    router.add_api_route("/cycles/{cycle_id}/commands/" + action, command_endpoint(action), methods=["POST"])
