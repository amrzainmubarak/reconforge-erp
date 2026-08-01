"""Human-governed integration and evidence-retention administration routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import (
    execute_postgres_security_governance,
    request_tenant_id,
    server_identity_enabled,
)
from reconforge.application.pagination import CursorCodec, CursorError, CursorPosition, cursor_scope_digest
from reconforge.application.security_governance import (
    IntegrationKind,
    SecurityGovernanceApplicationService,
    SecurityGovernanceError,
)
from reconforge.auth.models import LocalUser
from reconforge.infrastructure.postgres_security_governance import PostgresSecurityGovernanceRepository

router = APIRouter(prefix="/admin/security", tags=["security-governance"])
ManageSecurityPolicy = Annotated[LocalUser, Depends(require_permission("security.policy.manage"))]
PageLimit = Annotated[int, Query(ge=1, le=200)]
CursorToken = Annotated[str | None, Query(max_length=4096)]
ResultT = TypeVar("ResultT")


class IntegrationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["federation_link", "notification_route", "scim_credential", "service_account"]
    id: str
    status: Literal["active", "disabled", "expired"]
    lifecycle_version: int
    credential_count: int
    active_credential_count: int
    created_at: str
    expires_at: str | None
    last_used_at: str | None
    scope_digest: str
    state_digest: str


class PaginationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int
    returned: int
    next_cursor: str | None


class IntegrationPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    integrations: tuple[IntegrationResponse, ...]
    pagination: PaginationResponse


class DisableIntegrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_state_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: Literal["administrative_cleanup", "policy_change", "security_response", "user_request"]


class IntegrationDisableResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    integration: IntegrationResponse
    transitioned: bool
    revoked_credentials: int
    audit_event_id: str | None


class RetentionPolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    description: str
    data_classification: Literal["public", "internal", "confidential", "restricted"]
    duration_days: int
    active: bool
    lifecycle_version: int
    created_at: str
    updated_at: str
    retired_at: str | None
    state_digest: str


class RetentionPolicyPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policies: tuple[RetentionPolicyResponse, ...]
    pagination: PaginationResponse


class CreateRetentionPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    data_classification: Literal["public", "internal", "confidential", "restricted"]
    duration_days: int = Field(strict=True, ge=1, le=36_500)


class UpdateRetentionPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_lifecycle_version: int = Field(strict=True, ge=1)
    reason_code: Literal["administrative_cleanup", "policy_change", "security_response", "user_request"]
    description: str | None = Field(default=None, max_length=500)
    data_classification: Literal["public", "internal", "confidential", "restricted"] | None = None
    duration_days: int | None = Field(default=None, strict=True, ge=1, le=36_500)
    active: bool | None = Field(default=None, strict=True)


class RetentionPolicyChangeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: RetentionPolicyResponse
    transitioned: bool
    audit_event_id: str | None


class ApplyRetentionPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_retention_version: int = Field(strict=True, ge=1)
    reason_code: Literal[
        "policy_application", "regulatory_request", "security_response", "contractual_requirement"
    ]


class EvidenceRetentionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    policy_id: str
    policy_lifecycle_version: int
    retention_version: int
    previous_retention_until: str | None
    policy_retention_until: str
    effective_retention_until: str
    retention_extended: bool
    transitioned: bool
    audit_event_id: str | None
    state_digest: str


def _service(
    request: Request,
    operation: Callable[[SecurityGovernanceApplicationService, str], ResultT],
) -> ResultT:
    if not server_identity_enabled(request):
        raise APIError(
            status_code=503,
            code="security_governance_unavailable",
            message="Security governance requires the PostgreSQL server profile.",
        )

    def execute(repository: PostgresSecurityGovernanceRepository, tenant_id: str) -> ResultT:
        service = SecurityGovernanceApplicationService(
            repository,
            clock=lambda: datetime.now(UTC).replace(microsecond=0),
        )
        try:
            return operation(service, tenant_id)
        except SecurityGovernanceError as exc:
            status = 404 if exc.code.endswith("_not_found") else 409
            if exc.code.endswith(("_invalid", "_empty")):
                status = 400
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc

    return execute_postgres_security_governance(request, execute)


def _codec(request: Request) -> CursorCodec:
    codec = getattr(request.app.state, "cursor_codec", None)
    if not isinstance(codec, CursorCodec):
        raise APIError(
            status_code=503,
            code="cursor_pagination_not_configured",
            message="Security-governance pagination requires an operator-owned cursor signing key.",
        )
    return codec


def _cursor_scope(request: Request, *, resource: str, include_inactive: bool) -> str:
    return cursor_scope_digest(
        {
            "include_inactive": "true" if include_inactive else "false",
            "resource": resource,
            "tenant": request_tenant_id(request),
        }
    )


def _decode_cursor(
    request: Request,
    cursor: str | None,
    *,
    resource: str,
    include_inactive: bool,
    sort_key: str,
) -> CursorPosition | None:
    if cursor is None:
        return None
    try:
        position = _codec(request).decode(cursor)
    except CursorError as exc:
        raise APIError(status_code=400, code=exc.code, message="The governance cursor is invalid.") from exc
    if (
        position.sort_key != sort_key
        or position.direction != "asc"
        or position.scope_digest
        != _cursor_scope(request, resource=resource, include_inactive=include_inactive)
        or len(position.values) != 1
    ):
        raise APIError(
            status_code=400,
            code="cursor_context_mismatch",
            message="The governance cursor does not match this request.",
        )
    return position


def _encode_cursor(
    request: Request,
    *,
    resource: str,
    include_inactive: bool,
    sort_key: str,
    value: str | None,
    tie_breaker: str | None,
) -> str | None:
    if value is None or tie_breaker is None:
        return None
    return _codec(request).encode(
        CursorPosition(
            sort_key=sort_key,
            direction="asc",
            scope_digest=_cursor_scope(request, resource=resource, include_inactive=include_inactive),
            values=(value,),
            tie_breaker=tie_breaker,
        )
    )


@router.get("/integrations", response_model=IntegrationPageResponse)
def list_integrations(
    request: Request,
    current_user: ManageSecurityPolicy,
    limit: PageLimit = 100,
    cursor: CursorToken = None,
    include_inactive: Annotated[bool, Query()] = False,
) -> dict[str, object]:
    position = _decode_cursor(
        request,
        cursor,
        resource="security_integrations",
        include_inactive=include_inactive,
        sort_key="kind",
    )
    page = _service(
        request,
        lambda service, _tenant: service.list_integrations(
            include_inactive=include_inactive,
            limit=limit,
            after_kind=None if position is None else str(position.values[0]),
            after_integration_id=None if position is None else position.tie_breaker,
        ),
    )
    integrations = tuple(asdict(item) for item in page.items)
    next_cursor = _encode_cursor(
        request,
        resource="security_integrations",
        include_inactive=include_inactive,
        sort_key="kind",
        value=page.next_kind,
        tie_breaker=page.next_integration_id,
    )
    return {
        "integrations": integrations,
        "pagination": {"limit": limit, "returned": len(integrations), "next_cursor": next_cursor},
    }


@router.post(
    "/integrations/{kind}/{integration_id}/disable",
    response_model=IntegrationDisableResponse,
)
def disable_integration(
    kind: IntegrationKind,
    integration_id: str,
    payload: DisableIntegrationRequest,
    request: Request,
    current_user: ManageSecurityPolicy,
) -> dict[str, object]:
    result = _service(
        request,
        lambda service, _tenant: service.disable_integration(
            actor_user_id=current_user.id,
            kind=kind,
            integration_id=integration_id,
            expected_state_digest=payload.expected_state_digest,
            reason_code=payload.reason_code,
        ),
    )
    return asdict(result)


@router.get("/retention-policies", response_model=RetentionPolicyPageResponse)
def list_retention_policies(
    request: Request,
    current_user: ManageSecurityPolicy,
    limit: PageLimit = 100,
    cursor: CursorToken = None,
    include_retired: Annotated[bool, Query()] = False,
) -> dict[str, object]:
    position = _decode_cursor(
        request,
        cursor,
        resource="retention_policies",
        include_inactive=include_retired,
        sort_key="name",
    )
    page = _service(
        request,
        lambda service, _tenant: service.list_retention_policies(
            include_retired=include_retired,
            limit=limit,
            after_name=None if position is None else str(position.values[0]),
            after_policy_id=None if position is None else position.tie_breaker,
        ),
    )
    policies = tuple(asdict(item) for item in page.items)
    next_cursor = _encode_cursor(
        request,
        resource="retention_policies",
        include_inactive=include_retired,
        sort_key="name",
        value=page.next_name,
        tie_breaker=page.next_policy_id,
    )
    return {
        "policies": policies,
        "pagination": {"limit": limit, "returned": len(policies), "next_cursor": next_cursor},
    }


@router.post("/retention-policies", response_model=RetentionPolicyChangeResponse)
def create_retention_policy(
    payload: CreateRetentionPolicyRequest,
    request: Request,
    current_user: ManageSecurityPolicy,
) -> dict[str, object]:
    return asdict(
        _service(
            request,
            lambda service, _tenant: service.create_retention_policy(
                actor_user_id=current_user.id,
                name=payload.name,
                description=payload.description,
                data_classification=payload.data_classification,
                duration_days=payload.duration_days,
            ),
        )
    )


@router.patch("/retention-policies/{policy_id}", response_model=RetentionPolicyChangeResponse)
def update_retention_policy(
    policy_id: str,
    payload: UpdateRetentionPolicyRequest,
    request: Request,
    current_user: ManageSecurityPolicy,
) -> dict[str, object]:
    return asdict(
        _service(
            request,
            lambda service, _tenant: service.update_retention_policy(
                actor_user_id=current_user.id,
                policy_id=policy_id,
                expected_lifecycle_version=payload.expected_lifecycle_version,
                reason_code=payload.reason_code,
                description=payload.description,
                data_classification=payload.data_classification,
                duration_days=payload.duration_days,
                active=payload.active,
            ),
        )
    )


@router.post(
    "/retention-policies/{policy_id}/evidence/{evidence_id}",
    response_model=EvidenceRetentionResponse,
)
def apply_retention_policy(
    policy_id: str,
    evidence_id: str,
    payload: ApplyRetentionPolicyRequest,
    request: Request,
    current_user: ManageSecurityPolicy,
) -> dict[str, object]:
    return asdict(
        _service(
            request,
            lambda service, _tenant: service.apply_retention_policy(
                actor_user_id=current_user.id,
                policy_id=policy_id,
                evidence_id=evidence_id,
                expected_retention_version=payload.expected_retention_version,
                reason_code=payload.reason_code,
            ),
        )
    )
