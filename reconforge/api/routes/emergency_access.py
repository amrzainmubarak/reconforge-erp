"""Governed emergency-access lifecycle for the PostgreSQL identity profile."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal, TypeVar

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_current_user, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import execute_postgres_emergency, server_identity_enabled
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres_emergency_access import EmergencyAccessRecord
from reconforge.platform.common import ServerPrincipal, current_server_principal

router = APIRouter(prefix="/auth/emergency-access", tags=["auth", "security"])
T = TypeVar("T")

EmergencyApprover = Annotated[LocalUser, Depends(require_permission("security.emergency.approve"))]
EmergencyReviewer = Annotated[LocalUser, Depends(require_permission("security.emergency.review"))]


class EmergencyRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permissions: list[str] = Field(min_length=1, max_length=5)
    reason: str = Field(min_length=20, max_length=1000)
    incident_reference: str = Field(min_length=3, max_length=128)
    requested_minutes: int = Field(ge=5, le=60)


class EmergencyDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    note: str = Field(default="", max_length=1000)


class EmergencyActivationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class EmergencyReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    outcome: Literal["Confirmed", "Concern", "Incident"]
    note: str = Field(min_length=20, max_length=1000)


def _principal(request: Request, user: LocalUser) -> ServerPrincipal:
    if not server_identity_enabled(request):
        raise APIError(status_code=404, code="emergency_access_unavailable", message="Emergency access is unavailable.")
    principal = current_server_principal()
    if (
        not isinstance(principal, ServerPrincipal)
        or principal.principal_type != "user"
        or principal.user.id != user.id
        or principal.session_id is None
    ):
        raise APIError(status_code=403, code="human_principal_required", message="A human session is required.")
    return principal


def _payload(record: EmergencyAccessRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "requester_user_id": record.requester_user_id,
        "target_user_id": record.target_user_id,
        "permissions": sorted(record.permissions),
        "status": record.status,
        "reason": record.reason,
        "incident_reference": record.incident_reference,
        "requested_minutes": record.requested_minutes,
        "version": record.version,
        "requested_at": record.requested_at,
        "approved_by": record.approved_by,
        "activated_at": record.activated_at,
        "expires_at": record.expires_at,
        "reviewed_by": record.reviewed_by,
        "review_outcome": record.review_outcome,
    }


def _execute(request: Request, operation: Callable[[Any, str], T]) -> T:
    return execute_postgres_emergency(request, operation)


@router.post("/requests")
def request_access(
    body: EmergencyRequestBody,
    request: Request,
    current_user: LocalUser = Depends(get_current_user),
) -> dict[str, object]:
    principal = _principal(request, current_user)
    record = _execute(
        request,
        lambda repository, tenant_id: repository.request_access(
            tenant_id=tenant_id,
            requester_user_id=current_user.id,
            target_user_id=current_user.id,
            permissions=body.permissions,
            reason=body.reason,
            incident_reference=body.incident_reference,
            requested_minutes=body.requested_minutes,
            request_id=str(getattr(request.state, "request_id", "")),
        ),
    )
    del principal
    return {"request": _payload(record)}


@router.get("/requests")
def list_access(
    request: Request,
    current_user: LocalUser = Depends(get_current_user),
) -> dict[str, object]:
    principal = _principal(request, current_user)
    can_administer = bool(
        principal.step_up_active
        and principal.base_permissions.intersection({"security.emergency.approve", "security.emergency.review"})
    )
    records = _execute(
        request,
        lambda repository, tenant_id: repository.list_access(
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            can_administer=can_administer,
        ),
    )
    return {"requests": [_payload(item) for item in records]}


@router.post("/requests/{access_id}/approve")
def approve_access(
    access_id: str,
    body: EmergencyActivationBody,
    request: Request,
    current_user: EmergencyApprover,
) -> dict[str, object]:
    _principal(request, current_user)
    record = _execute(
        request,
        lambda repository, tenant_id: repository.approve(
            tenant_id=tenant_id,
            access_id=access_id,
            approver_user_id=current_user.id,
            expected_version=body.expected_version,
            request_id=str(getattr(request.state, "request_id", "")),
        ),
    )
    return {"request": _payload(record)}


@router.post("/requests/{access_id}/reject")
def reject_access(
    access_id: str,
    body: EmergencyDecisionBody,
    request: Request,
    current_user: EmergencyApprover,
) -> dict[str, object]:
    _principal(request, current_user)
    record = _execute(
        request,
        lambda repository, tenant_id: repository.reject(
            tenant_id=tenant_id,
            access_id=access_id,
            approver_user_id=current_user.id,
            expected_version=body.expected_version,
            note=body.note,
            request_id=str(getattr(request.state, "request_id", "")),
        ),
    )
    return {"request": _payload(record)}


@router.post("/requests/{access_id}/activate")
def activate_access(
    access_id: str,
    body: EmergencyActivationBody,
    request: Request,
    current_user: LocalUser = Depends(get_current_user),
) -> dict[str, object]:
    principal = _principal(request, current_user)
    record = _execute(
        request,
        lambda repository, tenant_id: repository.activate(
            tenant_id=tenant_id,
            access_id=access_id,
            target_user_id=current_user.id,
            session_id=principal.session_id or "",
            expected_version=body.expected_version,
            step_up_active=principal.step_up_active,
            request_id=str(getattr(request.state, "request_id", "")),
        ),
    )
    return {"request": _payload(record)}


@router.post("/requests/{access_id}/end")
def end_access(
    access_id: str,
    body: EmergencyDecisionBody,
    request: Request,
    current_user: LocalUser = Depends(get_current_user),
) -> dict[str, object]:
    principal = _principal(request, current_user)
    can_administer = principal.step_up_active and "security.emergency.approve" in principal.base_permissions
    record = _execute(
        request,
        lambda repository, tenant_id: repository.end_access(
            tenant_id=tenant_id,
            access_id=access_id,
            actor_user_id=current_user.id,
            expected_version=body.expected_version,
            actor_can_administer=can_administer,
            note=body.note,
            request_id=str(getattr(request.state, "request_id", "")),
        ),
    )
    return {"request": _payload(record)}


@router.post("/requests/{access_id}/review")
def review_access(
    access_id: str,
    body: EmergencyReviewBody,
    request: Request,
    current_user: EmergencyReviewer,
) -> dict[str, object]:
    _principal(request, current_user)
    record = _execute(
        request,
        lambda repository, tenant_id: repository.review(
            tenant_id=tenant_id,
            access_id=access_id,
            reviewer_user_id=current_user.id,
            expected_version=body.expected_version,
            outcome=body.outcome,
            note=body.note,
            request_id=str(getattr(request.state, "request_id", "")),
        ),
    )
    return {"request": _payload(record)}
