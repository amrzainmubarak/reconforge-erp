"""Authenticated operational posting over the dimensioned Finance Core."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import (
    enforce_server_scoped_permission,
    enforce_server_scoped_permissions,
    get_auth_db,
    get_current_user,
    require_any_permission,
    require_permission,
)
from reconforge.api.errors import APIError
from reconforge.api.finance_posting_contract import (
    project_posted_trial_balance,
    project_posting_effect,
    project_posting_preview,
    project_posting_reversal,
)
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.api.server_identity import request_execution_scope
from reconforge.application.finance_posting import FinancePostingApplicationService
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.platform.common import ServerPrincipal, current_server_principal
from reconforge.platform.inventory_values import code

router = APIRouter(prefix="/finance-core", tags=["finance-posting"])
READ_PERMISSIONS = frozenset({"finance_core.read", "finance_core.manage", "finance_core.validate", "finance_core.post"})
PostingRead = Annotated[LocalUser, Depends(require_any_permission(set(READ_PERMISSIONS)))]
PostingWrite = Annotated[LocalUser, Depends(require_permission("finance_core.post"))]


def _reversal_user(
    request: Request,
    current_user: LocalUser = Depends(get_current_user),
    connection: sqlite3.Connection | None = Depends(get_auth_db),
) -> LocalUser:
    for permission in ("finance_core.manage", "finance_core.reverse"):
        require_permission(permission)(request, current_user, connection)
    return current_user


_reversal_dependency = cast(Any, _reversal_user)
_reversal_dependency.__reconforge_permissions__ = frozenset({"finance_core.manage", "finance_core.reverse"})
_reversal_dependency.__reconforge_permission_mode__ = "all"
PostingReverse = Annotated[LocalUser, Depends(_reversal_user)]


class PostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=160)
    expected_validation_digest: str = Field(pattern="^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


class ReversalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=160)
    entry_number: str = Field(min_length=1, max_length=64)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(min_length=1, max_length=500)


def _actor(request: Request, user: LocalUser) -> PostingActor:
    principal = getattr(request.state, "server_principal", None) or current_server_principal()
    if not isinstance(principal, ServerPrincipal) or principal.user.id != user.id:
        raise APIError(status_code=503, code="posting_identity_unavailable", message="Operational posting requires a verified server identity and session assurance.")
    return PostingActor(user.id, user.username, principal.permissions, principal.principal_type, principal.step_up_active)


def _error(exc: FinancePostingError) -> APIError:
    if exc.code in {"posting_permission_denied", "posting_human_required", "posting_step_up_required", "posting_sod_denied", "posting_scope_denied"}:
        status = 403
    elif exc.code in {"posting_entry_not_found", "posting_effect_not_found"}:
        status = 404
    elif exc.code in {"posting_command_conflict", "posting_review_changed", "posting_source_conflict", "posting_state_invalid", "posting_period_closed"}:
        status = 409
    else:
        status = 400
    return APIError(status_code=status, code=exc.code, message=str(exc))


def _authority(request: Request, permissions: frozenset[str], snapshot: Mapping[str, Any] | None = None) -> None:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="posting_backend_unavailable", message="This operational posting API requires the PostgreSQL server profile.")
    scope = request_execution_scope(request)
    values: dict[str, Any] = {"organization_id": scope.organization_id, "entity_id": scope.legal_entity_id}
    if snapshot is not None:
        entry = snapshot["entry"]
        if entry["workspace_id"] != scope.workspace_id:
            raise APIError(status_code=403, code="workspace_scope_denied", message="Posting workspace is outside the authorized scope.")
        values = {"organization_id": entry["organization_id"], "entity_id": entry["legal_entity_id"]}
        precision = entry["currency_precision"]
        units = sum(line["debit_minor"] for line in snapshot["lines"])
        factor = 10 ** precision
        values["amount"] = Decimal(str(units)) if precision == 0 else Decimal(f"{units // factor}.{units % factor:0{precision}d}")
    enforce_server_scoped_permissions(
        request, permissions=permissions, tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id, **values,
    )


def _execute(
    request: Request,
    user: LocalUser,
    operation: Callable[[FinancePostingApplicationService, PostingActor, FinanceCoreExecutionScope], dict[str, Any]],
    *,
    organization_code: str = "",
    entity_code: str = "",
) -> dict[str, Any]:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="posting_backend_unavailable", message="This operational posting API requires the PostgreSQL server profile.")
    actor = _actor(request, user)

    def invoke(repository: Any, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        try:
            service = FinancePostingApplicationService(PostgresFinancePostingRepository(repository.connection, scope.tenant_id))
            return operation(service, actor, scope)
        except FinancePostingError as exc:
            raise _error(exc) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise APIError(status_code=503, code="posting_response_invalid", message="Posting response could not be verified.") from exc

    return execute_postgres_finance_core_scoped(request, invoke, organization_code=organization_code, entity_code=entity_code)


@router.get("/entries/{entry_id}/posting-preview")
def preview(request: Request, entry_id: str, current_user: PostingRead) -> dict[str, Any]:
    _authority(request, READ_PERMISSIONS)

    def run(service: FinancePostingApplicationService, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        value = service.preview(entry_id, actor=actor)
        _authority(request, READ_PERMISSIONS, value["snapshot"])
        return {"review": project_posting_preview(value)}

    return _execute(request, current_user, run)


@router.post("/entries/{entry_id}/post")
def post(request: Request, entry_id: str, payload: PostRequest, current_user: PostingWrite) -> dict[str, Any]:
    _authority(request, frozenset({"finance_core.post"}))

    def run(service: FinancePostingApplicationService, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        reviewed = service.preview(entry_id, actor=actor)
        _authority(request, frozenset({"finance_core.post"}), reviewed["snapshot"])
        value = service.post(entry_id, **payload.model_dump(), actor=actor)
        return {"posting": project_posting_effect(value)}

    return _execute(request, current_user, run)


@router.get("/postings/{effect_id}")
def get_effect(request: Request, effect_id: str, current_user: PostingRead) -> dict[str, Any]:
    _authority(request, READ_PERMISSIONS)

    def run(service: FinancePostingApplicationService, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        value = service.get_effect(effect_id, actor=actor)
        _authority(request, READ_PERMISSIONS, value["snapshot"])
        return {"posting": project_posting_effect(value)}

    return _execute(request, current_user, run)


@router.post("/postings/{effect_id}/reversal")
def prepare_reversal(request: Request, effect_id: str, payload: ReversalRequest, current_user: PostingReverse) -> dict[str, Any]:
    for permission in ("finance_core.reverse", "finance_core.manage"):
        scope = request_execution_scope(request)
        enforce_server_scoped_permission(request, permission=permission, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id, organization_id=scope.organization_id, entity_id=scope.legal_entity_id)

    def run(service: FinancePostingApplicationService, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        original = service.get_effect(effect_id, actor=actor)
        for permission in ("finance_core.reverse", "finance_core.manage"):
            _authority(request, frozenset({permission}), original["snapshot"])
        return {"reversal": project_posting_reversal(service.prepare_reversal(effect_id, **payload.model_dump(), actor=actor))}

    return _execute(request, current_user, run)


@router.get("/posted-trial-balance")
def posted_trial_balance(
    request: Request, current_user: PostingRead, period_id: str,
    organization_code: str, entity_code: str, workspace: str = "default",
) -> dict[str, Any]:
    _authority(request, READ_PERMISSIONS)
    scope = request_execution_scope(request)
    if workspace.strip() not in {"default", scope.workspace_id}:
        raise APIError(status_code=403, code="workspace_scope_denied", message="Posting workspace is outside the authorized scope.")
    def run(service: FinancePostingApplicationService, actor: PostingActor, bound: FinanceCoreExecutionScope) -> dict[str, Any]:
        value = service.posted_trial_balance(period_id=period_id, organization_code=bound.organization_code, entity_code=bound.entity_code, workspace=bound.workspace_id, actor=actor)
        return {"trial_balance": project_posted_trial_balance(value)}

    return _execute(request, current_user, run, organization_code=code(organization_code, "Organization code"), entity_code=code(entity_code, "Entity code"))
