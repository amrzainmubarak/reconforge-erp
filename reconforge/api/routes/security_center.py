"""Disclosure-bounded administration and security overview route."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import enforce_server_scoped_permissions, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import execute_postgres_security_center, server_identity_enabled
from reconforge.application.security_center import SecurityCenterApplicationService, SecurityCenterRuntime
from reconforge.auth.models import LocalUser
from reconforge.auth.webauthn_config import WebAuthnRuntime

router = APIRouter(prefix="/admin/security", tags=["administration-security"])
SecurityCenterRead = Annotated[LocalUser, Depends(require_permission("security.center.read"))]


class IdentityStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_users: int
    active_users: int
    disabled_users: int
    locked_users: int
    active_users_without_roles: int
    roles: int
    permissions: int
    role_permission_bindings: int


class SessionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active_sessions: int
    revoked_sessions: int
    expired_unrevoked_sessions: int
    active_step_up_assertions: int
    active_webauthn_credentials: int
    users_with_active_webauthn: int


class IntegrationStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configured_federation_providers: int
    federation_air_gap_mode: bool
    linked_federation_providers: int
    active_federation_links: int
    disabled_federation_links: int
    scim_domains: int
    active_scim_users: int
    active_scim_credentials: int
    enabled_service_accounts: int
    active_service_account_credentials: int
    enabled_notification_routes: int
    webauthn_required_for_privileged_actions: bool


class PolicyStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active_scope_grants: int
    pending_emergency_requests: int
    active_emergency_access: int
    overdue_emergency_reviews: int


class RetentionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_records: int
    evidence_with_retention: int
    evidence_retention_expired: int
    evidence_unverified: int
    evidence_verification_failed: int


class AuditStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audit_events: int
    chain_verification: Literal["not_evaluated_use_audit_verify_endpoint"]


class AttentionItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["medium", "high"]
    code: str
    count: int


class SecurityCenterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    as_of: str
    tenant_scope_digest: str
    posture: Literal["attention_required", "observed_no_count_based_attention"]
    claim_boundary: Literal["operational_snapshot_not_security_assurance"]
    identity: IdentityStatusResponse
    sessions: SessionStatusResponse
    integrations: IntegrationStatusResponse
    policy: PolicyStatusResponse
    retention: RetentionStatusResponse
    audit: AuditStatusResponse
    attention_items: list[AttentionItemResponse]
    snapshot_digest: str


@router.get("/overview", response_model=SecurityCenterResponse)
def security_overview(request: Request, current_user: SecurityCenterRead) -> SecurityCenterResponse:
    """Return a tenant-scoped operational snapshot without identity or credential details."""

    del current_user
    if not server_identity_enabled(request):
        raise APIError(status_code=404, code="security_center_unavailable", message="Security center is unavailable.")
    from reconforge.api.server_identity import request_tenant_id

    enforce_server_scoped_permissions(
        request,
        permissions=frozenset({"security.center.read"}),
        tenant_id=request_tenant_id(request),
        workspace_id=None,
    )
    runtime = SecurityCenterRuntime(
        configured_federation_providers=len(getattr(request.app.state, "federation_providers", {})),
        federation_air_gap_mode=bool(getattr(request.app.state, "federation_air_gap_mode", False)),
        webauthn_required_for_privileged_actions=isinstance(
            getattr(request.app.state, "webauthn_runtime", None), WebAuthnRuntime
        ),
    )
    payload = execute_postgres_security_center(
        request,
        lambda repository, tenant: SecurityCenterApplicationService(
            repository,
            clock=lambda: datetime.now(UTC).replace(microsecond=0),
        )
        .snapshot(tenant_id=tenant, runtime=runtime)
        .to_payload(),
    )
    return SecurityCenterResponse.model_validate(payload)
