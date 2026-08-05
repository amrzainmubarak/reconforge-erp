"""Human-governed PostgreSQL identity and session administration routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import enforce_server_tenant_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import (
    execute_postgres_identity_administration,
    request_tenant_id,
    server_identity_enabled,
)
from reconforge.application.identity_administration import (
    IdentityAdministrationApplicationService,
    IdentityAdministrationError,
)
from reconforge.application.pagination import CursorCodec, CursorError, CursorPosition, cursor_scope_digest
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres_identity_administration import (
    PostgresIdentityAdministrationRepository,
)
from reconforge.platform.common import current_server_principal

router = APIRouter(prefix="/admin/identity", tags=["identity-administration"])
ManageIdentity = Annotated[LocalUser, Depends(require_permission("users.manage"))]
PageLimit = Annotated[int, Query(ge=1, le=200)]
CursorToken = Annotated[str | None, Query(max_length=4096)]
ResultT = TypeVar("ResultT")


class IdentityUserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    username: str
    display_name: str
    disabled: bool
    lifecycle_version: int
    roles: tuple[str, ...]
    active_sessions: int
    created_at: str
    disabled_at: str | None
    state_digest: str


class IdentitySessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    user_id: str
    username: str
    status: Literal["active", "expired", "revoked"]
    lifecycle_version: int
    created_at: str
    expires_at: str
    last_used_at: str | None
    revoked_at: str | None
    revocation_reason_code: str | None
    client_ip_recorded: bool
    user_agent_recorded: bool
    state_digest: str


class PaginationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int
    returned: int
    next_cursor: str | None


class IdentityUserPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    users: tuple[IdentityUserResponse, ...]
    pagination: PaginationResponse


class IdentitySessionPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessions: tuple[IdentitySessionResponse, ...]
    pagination: PaginationResponse


class UserStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disabled: bool = Field(strict=True)
    expected_lifecycle_version: int = Field(strict=True, ge=1)


class UserStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user: IdentityUserResponse
    transitioned: bool
    revoked_sessions: int
    audit_event_id: str | None


class SessionRevocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_lifecycle_version: int = Field(strict=True, ge=1)
    reason_code: Literal["access_change", "administrative_cleanup", "security_response", "user_request"]


class SessionRevocationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session: IdentitySessionResponse
    transitioned: bool
    revoked_current_session: bool
    audit_event_id: str | None


def _service(
    request: Request,
    operation: Callable[[IdentityAdministrationApplicationService, str], ResultT],
    *,
    permission: str = "users.manage",
) -> ResultT:
    if not server_identity_enabled(request):
        raise APIError(
            status_code=503,
            code="identity_administration_unavailable",
            message="Identity administration requires the PostgreSQL server profile.",
        )

    def execute(repository: PostgresIdentityAdministrationRepository, tenant_id: str) -> ResultT:
        enforce_server_tenant_permission(request, permission=permission, tenant_id=tenant_id)
        service = IdentityAdministrationApplicationService(
            repository,
            clock=lambda: datetime.now(UTC).replace(microsecond=0),
        )
        try:
            return operation(service, tenant_id)
        except IdentityAdministrationError as exc:
            status = 404 if exc.code.endswith("_not_found") else 409
            if exc.code.endswith(("_invalid", "_time_invalid")):
                status = 400
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc

    return execute_postgres_identity_administration(request, execute)


def _codec(request: Request) -> CursorCodec:
    codec = getattr(request.app.state, "cursor_codec", None)
    if not isinstance(codec, CursorCodec):
        raise APIError(
            status_code=503,
            code="cursor_pagination_not_configured",
            message="Identity pagination requires an operator-owned cursor signing key.",
        )
    return codec


def _decode_cursor(
    request: Request,
    *,
    cursor: str | None,
    resource: str,
    filter_user_id: str,
    sort_key: str,
    direction: str,
) -> CursorPosition | None:
    if cursor is None:
        return None
    tenant = request_tenant_id(request)
    scope = cursor_scope_digest(
        {"filter_user_id": filter_user_id, "resource": resource, "tenant": tenant}
    )
    try:
        position = _codec(request).decode(cursor)
    except CursorError as exc:
        raise APIError(status_code=400, code=exc.code, message="The identity cursor is invalid.") from exc
    if (
        position.sort_key != sort_key
        or position.direction != direction
        or position.scope_digest != scope
        or len(position.values) != 1
    ):
        raise APIError(
            status_code=400,
            code="cursor_context_mismatch",
            message="The identity cursor does not match this request.",
        )
    return position


def _encode_cursor(
    request: Request,
    *,
    resource: str,
    filter_user_id: str,
    sort_key: str,
    direction: str,
    value: str | None,
    tie_breaker: str | None,
) -> str | None:
    if value is None or tie_breaker is None:
        return None
    scope = cursor_scope_digest(
        {
            "filter_user_id": filter_user_id,
            "resource": resource,
            "tenant": request_tenant_id(request),
        }
    )
    return _codec(request).encode(
        CursorPosition(
            sort_key=sort_key,
            direction=direction,
            scope_digest=scope,
            values=(value,),
            tie_breaker=tie_breaker,
        )
    )


@router.get("/users", response_model=IdentityUserPageResponse)
def list_identity_users(
    request: Request,
    current_user: ManageIdentity,
    limit: PageLimit = 100,
    cursor: CursorToken = None,
) -> dict[str, object]:
    """List authoritative PostgreSQL identities without credentials or email."""

    position = _decode_cursor(
        request,
        cursor=cursor,
        resource="identity_users",
        filter_user_id="",
        sort_key="username",
        direction="asc",
    )
    page = _service(
        request,
        lambda service, _tenant: service.list_users(
            limit=limit,
            after_username=None if position is None else str(position.values[0]),
            after_user_id=None if position is None else position.tie_breaker,
        ),
    )
    next_cursor = _encode_cursor(
        request,
        resource="identity_users",
        filter_user_id="",
        sort_key="username",
        direction="asc",
        value=page.next_username,
        tie_breaker=page.next_user_id,
    )
    users = tuple(asdict(item) for item in page.items)
    return {"users": users, "pagination": {"limit": limit, "returned": len(users), "next_cursor": next_cursor}}


@router.post("/users/{user_id}/status", response_model=UserStatusResponse)
def set_identity_user_status(
    user_id: str,
    payload: UserStatusRequest,
    request: Request,
    current_user: ManageIdentity,
) -> dict[str, object]:
    """Optimistically disable or re-enable one identity; disabling revokes every session."""

    result = _service(
        request,
        lambda service, _tenant: service.set_user_disabled(
            actor_user_id=current_user.id,
            user_id=user_id,
            disabled=payload.disabled,
            expected_lifecycle_version=payload.expected_lifecycle_version,
        ),
    )
    return asdict(result)


@router.get("/sessions", response_model=IdentitySessionPageResponse)
def list_identity_sessions(
    request: Request,
    current_user: ManageIdentity,
    limit: PageLimit = 100,
    cursor: CursorToken = None,
    user_id: Annotated[str | None, Query(max_length=160)] = None,
) -> dict[str, object]:
    """List session lifecycle metadata without tokens, IP addresses, or user-agent values."""

    filter_user = "" if user_id is None else user_id.strip().casefold()
    position = _decode_cursor(
        request,
        cursor=cursor,
        resource="identity_sessions",
        filter_user_id=filter_user,
        sort_key="created_at",
        direction="desc",
    )
    page = _service(
        request,
        lambda service, _tenant: service.list_sessions(
            limit=limit,
            user_id=user_id,
            after_created_at=None if position is None else str(position.values[0]),
            after_session_id=None if position is None else position.tie_breaker,
        ),
    )
    next_cursor = _encode_cursor(
        request,
        resource="identity_sessions",
        filter_user_id=filter_user,
        sort_key="created_at",
        direction="desc",
        value=page.next_created_at,
        tie_breaker=page.next_session_id,
    )
    sessions = tuple(asdict(item) for item in page.items)
    return {
        "sessions": sessions,
        "pagination": {"limit": limit, "returned": len(sessions), "next_cursor": next_cursor},
    }


@router.post("/sessions/{session_id}/revoke", response_model=SessionRevocationResponse)
def revoke_identity_session(
    session_id: str,
    payload: SessionRevocationRequest,
    request: Request,
    current_user: ManageIdentity,
) -> dict[str, object]:
    """Optimistically revoke one session and append bounded audit evidence."""

    principal = current_server_principal()
    if principal is None or principal.principal_type != "user" or principal.session_id is None:
        raise APIError(status_code=403, code="human_principal_required", message="A human session is required.")
    result = _service(
        request,
        lambda service, _tenant: service.revoke_session(
            actor_user_id=current_user.id,
            current_session_id=principal.session_id or "",
            session_id=session_id,
            expected_lifecycle_version=payload.expected_lifecycle_version,
            reason_code=payload.reason_code,
        ),
    )
    return asdict(result)
