"""Human-governed, redacted audit browsing for the PostgreSQL server profile."""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict

from reconforge.api.dependencies import enforce_server_scoped_permissions, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_audit import (
    execute_postgres_audit_administration,
    server_audit_administration_enabled,
)
from reconforge.api.server_identity import request_tenant_id
from reconforge.application.audit_browsing import (
    AuditBrowsingApplicationService,
    AuditBrowsingError,
    AuditBrowsingRepositoryProtocol,
)
from reconforge.application.pagination import CursorCodec, CursorError, CursorPosition, cursor_scope_digest
from reconforge.auth.models import LocalUser

router = APIRouter(prefix="/admin/audit", tags=["audit-administration"])
AuditRead = Annotated[LocalUser, Depends(require_permission("audit.read"))]
AuditVerify = Annotated[LocalUser, Depends(require_permission("audit.verify"))]
PageLimit = Annotated[int, Query(ge=1, le=200)]
CursorToken = Annotated[str | None, Query(max_length=4096)]


class RedactedAuditEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["domain", "ledger_control"]
    event_id: str
    sequence: int
    occurred_at: str
    action: str
    object_type: str
    actor_digest: str
    object_digest: str
    metadata_digest: str
    previous_event_hash: str
    event_hash: str
    before_state_hash: str | None
    after_state_hash: str | None


class AuditPaginationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int
    returned: int
    next_cursor: str | None


class RedactedAuditPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: tuple[RedactedAuditEventResponse, ...]
    pagination: AuditPaginationResponse
    disclosure: Literal["redacted_no_raw_subject_object_reason_or_metadata"]
    chain_model: Literal["independent_source_chains_no_global_chain"]


class AuditChainVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["domain", "ledger_control"]
    ok: bool
    checked_events: int
    head_hash: str
    issue_codes: tuple[str, ...]


class AuditVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    chains: tuple[AuditChainVerificationResponse, ...]
    chain_model: Literal["independent_source_chains_no_global_chain"]


def _codec(request: Request) -> CursorCodec:
    codec = getattr(request.app.state, "cursor_codec", None)
    if not isinstance(codec, CursorCodec):
        raise APIError(
            status_code=503,
            code="cursor_pagination_not_configured",
            message="Audit browsing requires an operator-owned cursor signing key.",
        )
    return codec


def _scope(request: Request) -> str:
    return cursor_scope_digest({"resource": "audit_events", "tenant": request_tenant_id(request)})


def _enforce_server_policy(request: Request, *, permission: str) -> None:
    """Bind tenant-wide audit access to the authenticated request tenant."""

    enforce_server_scoped_permissions(
        request,
        permissions=frozenset({permission}),
        tenant_id=request_tenant_id(request),
        workspace_id=None,
    )


def _decode_cursor(request: Request, cursor: str | None) -> tuple[str, Literal["domain", "ledger_control"], str] | None:
    if cursor is None:
        return None
    try:
        position = _codec(request).decode(cursor)
    except CursorError as exc:
        raise APIError(status_code=400, code=exc.code, message="The audit cursor is invalid.") from exc
    if (
        position.sort_key != "occurred_at"
        or position.direction != "asc"
        or position.scope_digest != _scope(request)
        or len(position.values) != 2
        or not isinstance(position.values[0], str)
        or position.values[1] not in {"domain", "ledger_control"}
    ):
        raise APIError(status_code=400, code="cursor_context_mismatch", message="The audit cursor does not match this request.")
    return position.values[0], cast(Literal["domain", "ledger_control"], position.values[1]), position.tie_breaker


def _encode_cursor(
    request: Request,
    *,
    occurred_at: str,
    source: Literal["domain", "ledger_control"],
    event_id: str,
) -> str:
    return _codec(request).encode(
        CursorPosition(
            sort_key="occurred_at",
            direction="asc",
            scope_digest=_scope(request),
            values=(occurred_at, source),
            tie_breaker=event_id,
        )
    )


@router.get("/events", response_model=RedactedAuditPageResponse)
def list_audit_events(
    request: Request,
    current_user: AuditRead,
    limit: PageLimit = 100,
    cursor: CursorToken = None,
) -> dict[str, object]:
    """Browse two source chains without returning raw audit payload fields."""

    if not server_audit_administration_enabled(request):
        raise APIError(
            status_code=503,
            code="audit_administration_unavailable",
            message="Audit administration requires the PostgreSQL server profile.",
        )
    _enforce_server_policy(request, permission="audit.read")
    position = _decode_cursor(request, cursor)

    def operation(repository: AuditBrowsingRepositoryProtocol, _tenant: str) -> dict[str, object]:
        service = AuditBrowsingApplicationService(repository)
        try:
            page = service.list_events(
                limit=limit,
                after_occurred_at=None if position is None else position[0],
                after_source=None if position is None else position[1],
                after_event_id=None if position is None else position[2],
            )
        except AuditBrowsingError as exc:
            raise APIError(status_code=409, code="audit_administration_conflict", message=str(exc)) from exc
        next_cursor = None
        if page.has_more and page.events:
            final = page.events[-1]
            next_cursor = _encode_cursor(
                request,
                occurred_at=final.occurred_at,
                source=final.source,
                event_id=final.event_id,
            )
        return {
            "events": [event.__dict__ for event in page.events],
            "pagination": {"limit": limit, "returned": len(page.events), "next_cursor": next_cursor},
            "disclosure": "redacted_no_raw_subject_object_reason_or_metadata",
            "chain_model": "independent_source_chains_no_global_chain",
        }

    return execute_postgres_audit_administration(request, operation)


@router.get("/verify", response_model=AuditVerificationResponse)
def verify_audit_events(request: Request, current_user: AuditVerify) -> dict[str, object]:
    """Verify both independent PostgreSQL audit chains for the request tenant."""

    if not server_audit_administration_enabled(request):
        raise APIError(
            status_code=503,
            code="audit_administration_unavailable",
            message="Audit administration requires the PostgreSQL server profile.",
        )
    _enforce_server_policy(request, permission="audit.verify")

    def operation(repository: AuditBrowsingRepositoryProtocol, _tenant: str) -> dict[str, object]:
        service = AuditBrowsingApplicationService(repository)
        try:
            result = service.verify()
        except AuditBrowsingError as exc:
            raise APIError(status_code=409, code="audit_administration_conflict", message=str(exc)) from exc
        return {
            "ok": result.ok,
            "chains": [chain.__dict__ for chain in result.chains],
            "chain_model": "independent_source_chains_no_global_chain",
        }

    return execute_postgres_audit_administration(request, operation)
