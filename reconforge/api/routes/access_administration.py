"""Human-governed PostgreSQL role and access-policy administration routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import (
    execute_postgres_access_administration,
    request_tenant_id,
    server_identity_enabled,
)
from reconforge.application.access_administration import (
    AccessAdministrationApplicationService,
    AccessAdministrationError,
)
from reconforge.application.pagination import CursorCodec, CursorError, CursorPosition, cursor_scope_digest
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres_access_administration import PostgresAccessAdministrationRepository

router = APIRouter(prefix="/admin/access", tags=["access-administration"])
ManageAccess = Annotated[LocalUser, Depends(require_permission("roles.manage"))]
PageLimit = Annotated[int, Query(ge=1, le=200)]
CursorToken = Annotated[str | None, Query(max_length=4096)]
ResultT = TypeVar("ResultT")


class AccessPermissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    active_role_count: int
    state_digest: str


class AccessRoleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    description: str
    active: bool
    lifecycle_version: int
    permissions: tuple[str, ...]
    active_user_count: int
    created_at: str
    updated_at: str
    retired_at: str | None
    state_digest: str


class PaginationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int
    returned: int
    next_cursor: str | None


class AccessRolePageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: tuple[AccessRoleResponse, ...]
    pagination: PaginationResponse


class CreateAccessRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    permissions: tuple[str, ...] = Field(default=(), max_length=256)


class UpdateAccessRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_lifecycle_version: int = Field(strict=True, ge=1)
    description: str | None = Field(default=None, max_length=500)
    active: bool | None = Field(default=None, strict=True)


class ReplaceRolePermissionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_lifecycle_version: int = Field(strict=True, ge=1)
    permissions: tuple[str, ...] = Field(max_length=256)


class ReplaceUserRolesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_user_lifecycle_version: int = Field(strict=True, ge=1)
    role_ids: tuple[str, ...] = Field(max_length=64)


class AccessRoleChangeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: AccessRoleResponse
    transitioned: bool
    revoked_sessions: int
    audit_event_id: str | None


class UserRoleAssignmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    username: str
    lifecycle_version: int
    role_ids: tuple[str, ...]
    role_names: tuple[str, ...]
    transitioned: bool
    revoked_sessions: int
    audit_event_id: str | None
    state_digest: str


def _service(
    request: Request,
    operation: Callable[[AccessAdministrationApplicationService, str], ResultT],
) -> ResultT:
    if not server_identity_enabled(request):
        raise APIError(
            status_code=503,
            code="access_administration_unavailable",
            message="Access administration requires the PostgreSQL server profile.",
        )

    def execute(repository: PostgresAccessAdministrationRepository, tenant_id: str) -> ResultT:
        service = AccessAdministrationApplicationService(
            repository,
            clock=lambda: datetime.now(UTC).replace(microsecond=0),
        )
        try:
            return operation(service, tenant_id)
        except AccessAdministrationError as exc:
            status = 404 if exc.code.endswith("_not_found") else 409
            if exc.code.endswith(("_invalid", "_too_large")):
                status = 400
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc

    return execute_postgres_access_administration(request, execute)


def _codec(request: Request) -> CursorCodec:
    codec = getattr(request.app.state, "cursor_codec", None)
    if not isinstance(codec, CursorCodec):
        raise APIError(
            status_code=503,
            code="cursor_pagination_not_configured",
            message="Access pagination requires an operator-owned cursor signing key.",
        )
    return codec


def _decode_role_cursor(request: Request, cursor: str | None, *, include_retired: bool) -> CursorPosition | None:
    if cursor is None:
        return None
    scope = cursor_scope_digest(
        {
            "include_retired": "true" if include_retired else "false",
            "resource": "access_roles",
            "tenant": request_tenant_id(request),
        }
    )
    try:
        position = _codec(request).decode(cursor)
    except CursorError as exc:
        raise APIError(status_code=400, code=exc.code, message="The access cursor is invalid.") from exc
    if (
        position.sort_key != "name"
        or position.direction != "asc"
        or position.scope_digest != scope
        or len(position.values) != 1
    ):
        raise APIError(
            status_code=400,
            code="cursor_context_mismatch",
            message="The access cursor does not match this request.",
        )
    return position


def _encode_role_cursor(
    request: Request,
    *,
    include_retired: bool,
    name: str | None,
    role_id: str | None,
) -> str | None:
    if name is None or role_id is None:
        return None
    scope = cursor_scope_digest(
        {
            "include_retired": "true" if include_retired else "false",
            "resource": "access_roles",
            "tenant": request_tenant_id(request),
        }
    )
    return _codec(request).encode(
        CursorPosition(
            sort_key="name",
            direction="asc",
            scope_digest=scope,
            values=(name,),
            tie_breaker=role_id,
        )
    )


@router.get("/permissions", response_model=tuple[AccessPermissionResponse, ...])
def list_access_permissions(request: Request, current_user: ManageAccess) -> tuple[dict[str, object], ...]:
    """List the closed tenant permission registry without mutation capability."""

    permissions = _service(request, lambda service, _tenant: service.list_permissions())
    return tuple(asdict(permission) for permission in permissions)


@router.get("/roles", response_model=AccessRolePageResponse)
def list_access_roles(
    request: Request,
    current_user: ManageAccess,
    limit: PageLimit = 100,
    cursor: CursorToken = None,
    include_retired: Annotated[bool, Query()] = False,
) -> dict[str, object]:
    """List authoritative PostgreSQL roles with signed keyset pagination."""

    position = _decode_role_cursor(request, cursor, include_retired=include_retired)
    page = _service(
        request,
        lambda service, _tenant: service.list_roles(
            limit=limit,
            include_retired=include_retired,
            after_name=None if position is None else str(position.values[0]),
            after_role_id=None if position is None else position.tie_breaker,
        ),
    )
    roles = tuple(asdict(role) for role in page.items)
    next_cursor = _encode_role_cursor(
        request,
        include_retired=include_retired,
        name=page.next_name,
        role_id=page.next_role_id,
    )
    return {"roles": roles, "pagination": {"limit": limit, "returned": len(roles), "next_cursor": next_cursor}}


@router.post("/roles", response_model=AccessRoleChangeResponse)
def create_access_role(
    payload: CreateAccessRoleRequest,
    request: Request,
    current_user: ManageAccess,
) -> dict[str, object]:
    result = _service(
        request,
        lambda service, _tenant: service.create_role(
            actor_user_id=current_user.id,
            name=payload.name,
            description=payload.description,
            permissions=payload.permissions,
        ),
    )
    return asdict(result)


@router.patch("/roles/{role_id}", response_model=AccessRoleChangeResponse)
def update_access_role(
    role_id: str,
    payload: UpdateAccessRoleRequest,
    request: Request,
    current_user: ManageAccess,
) -> dict[str, object]:
    result = _service(
        request,
        lambda service, _tenant: service.update_role(
            actor_user_id=current_user.id,
            role_id=role_id,
            expected_lifecycle_version=payload.expected_lifecycle_version,
            description=payload.description,
            active=payload.active,
        ),
    )
    return asdict(result)


@router.put("/roles/{role_id}/permissions", response_model=AccessRoleChangeResponse)
def replace_access_role_permissions(
    role_id: str,
    payload: ReplaceRolePermissionsRequest,
    request: Request,
    current_user: ManageAccess,
) -> dict[str, object]:
    result = _service(
        request,
        lambda service, _tenant: service.replace_role_permissions(
            actor_user_id=current_user.id,
            role_id=role_id,
            permissions=payload.permissions,
            expected_lifecycle_version=payload.expected_lifecycle_version,
        ),
    )
    return asdict(result)


@router.put("/users/{user_id}/roles", response_model=UserRoleAssignmentResponse)
def replace_access_user_roles(
    user_id: str,
    payload: ReplaceUserRolesRequest,
    request: Request,
    current_user: ManageAccess,
) -> dict[str, object]:
    result = _service(
        request,
        lambda service, _tenant: service.replace_user_roles(
            actor_user_id=current_user.id,
            user_id=user_id,
            role_ids=payload.role_ids,
            expected_user_lifecycle_version=payload.expected_user_lifecycle_version,
        ),
    )
    return asdict(result)
