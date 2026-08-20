"""Human-governed server authority for workspace and entity scopes."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import enforce_server_tenant_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import execute_postgres_identity, request_tenant_id, server_identity_enabled
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.platform.common import platform_id

router = APIRouter(prefix="/scope-grants", tags=["scope-authority"])
ManageScope = Annotated[LocalUser, Depends(require_permission("roles.manage"))]


class ScopeGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_type: Literal["user", "service_account"]
    principal_id: str = Field(min_length=1, max_length=128)
    scope_type: Literal["workspace", "organization", "legal_entity"]
    scope_id: str = Field(min_length=1, max_length=64)


class ScopeGrantRevocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


def _require_server(request: Request) -> None:
    if not server_identity_enabled(request):
        raise APIError(status_code=404, code="scope_authority_unavailable", message="Scope authority is unavailable.")


@router.get("/{principal_type}/{principal_id}")
def list_scope_grants(
    principal_type: Literal["user", "service_account"],
    principal_id: str,
    request: Request,
    current_user: ManageScope,
) -> dict[str, object]:
    _require_server(request)
    enforce_server_tenant_permission(request, permission="roles.manage", tenant_id=request_tenant_id(request))
    try:
        grants = execute_postgres_identity(
            request,
            lambda identity, tenant: PostgresScopeAuthorityRepository(identity.connection).list_active(
                tenant_id=tenant, principal_type=principal_type, principal_id=principal_id
            ),
        )
    except ValueError as exc:
        raise APIError(status_code=400, code="scope_grant_invalid", message=str(exc)) from exc
    return {"grants": grants}


@router.post("")
def create_scope_grant(
    payload: ScopeGrantRequest,
    request: Request,
    current_user: ManageScope,
) -> dict[str, object]:
    _require_server(request)
    enforce_server_tenant_permission(request, permission="roles.manage", tenant_id=request_tenant_id(request))
    grant_id = platform_id(
        "SCOPE", payload.principal_type, payload.principal_id, payload.scope_type, payload.scope_id
    ).lower()
    try:
        execute_postgres_identity(
            request,
            lambda identity, tenant: PostgresScopeAuthorityRepository(identity.connection).grant(
                tenant_id=tenant,
                grant_id=grant_id,
                principal_type=payload.principal_type,
                principal_id=payload.principal_id,
                scope_type=payload.scope_type,
                scope_id=payload.scope_id,
                actor_id=current_user.id,
            ),
        )
    except ValueError as exc:
        raise APIError(status_code=400, code="scope_grant_invalid", message=str(exc)) from exc
    return {"grant_id": grant_id, "status": "active"}


@router.post("/{grant_id}/revoke")
def revoke_scope_grant(
    grant_id: str,
    payload: ScopeGrantRevocation,
    request: Request,
    current_user: ManageScope,
) -> dict[str, object]:
    _require_server(request)
    enforce_server_tenant_permission(request, permission="roles.manage", tenant_id=request_tenant_id(request))
    try:
        execute_postgres_identity(
            request,
            lambda identity, tenant: PostgresScopeAuthorityRepository(identity.connection).revoke(
                tenant_id=tenant,
                grant_id=grant_id,
                actor_id=current_user.id,
                reason=payload.reason,
            ),
        )
    except ValueError as exc:
        raise APIError(status_code=404, code="scope_grant_not_found", message=str(exc)) from exc
    return {"grant_id": grant_id, "status": "revoked"}
