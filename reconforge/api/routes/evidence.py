"""Tenant-scoped evidence registry routes."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_local_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_evidence import execute_postgres_evidence, server_evidence_enabled
from reconforge.application.pagination import (
    CursorCodec,
    CursorError,
    KeysetPaginator,
    SortDefinition,
    cursor_scope_digest,
)
from reconforge.auth import AuthServiceError, LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.platform.common import PlatformError
from reconforge.platform.evidence import EvidenceRegistryService

router = APIRouter(prefix="/evidence", tags=["evidence"])
MAX_LIMIT = 1_000

EvidenceRead = Annotated[LocalUser, Depends(require_any_permission({"evidence.read", "evidence.manage"}))]
EvidenceManage = Annotated[LocalUser, Depends(require_permission("evidence.manage"))]
EvidenceVerify = Annotated[LocalUser, Depends(require_permission("evidence.verify"))]
PageLimit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]
CursorToken = Annotated[str | None, Query(max_length=4096)]


def _cursor_page(
    request: Request,
    records: list[dict[str, object]],
    *,
    status: str,
    limit: int,
    cursor: str | None,
) -> tuple[list[dict[str, object]], str | None]:
    codec = getattr(request.app.state, "cursor_codec", None)
    if not isinstance(codec, CursorCodec):
        raise APIError(
            status_code=503,
            code="cursor_pagination_not_configured",
            message="Cursor pagination requires an operator-configured signing key.",
        )
    tenant = request.headers.get("x-reconforge-tenant", "local")
    scope = cursor_scope_digest({"resource": "evidence", "status": status.casefold(), "tenant": tenant})
    paginator = KeysetPaginator(codec, (SortDefinition("created", ("created_at",)),))
    try:
        page = paginator.page(
            records, sort_key="created", direction="desc", scope_digest=scope, limit=limit, cursor=cursor
        )
    except CursorError as exc:
        raise APIError(
            status_code=400, code=exc.code, message="The pagination cursor is invalid for this request."
        ) from exc
    return [dict(record) for record in page.items], page.next_cursor


class EvidenceRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=64)
    evidence_code: str = Field(min_length=1, max_length=64)
    source_name: str = Field(min_length=1, max_length=512)
    checksum_sha256: str = Field(min_length=64, max_length=64)
    source_reference: str = Field(default="", max_length=2_048)
    provenance_type: str = Field(default="external-reference", max_length=64)
    redaction_status: str = Field(default="unknown", max_length=64)
    evidence_status: str = Field(default="Available", max_length=64)
    storage_backend: str = Field(default="external-reference", max_length=64)
    storage_tenant_id: str = Field(default="", max_length=64)
    storage_key: str = Field(default="", max_length=1_024)
    storage_version_id: str = Field(default="", max_length=255)
    content_type: str = Field(default="application/octet-stream", max_length=255)
    byte_size: int = Field(default=0, ge=0, le=10**12)
    retention_until: str | None = None
    reason: str = Field(default="", max_length=500)


class EvidenceLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str = Field(min_length=1, max_length=100)
    object_id: str = Field(min_length=1, max_length=160)
    link_type: str = Field(default="support", min_length=1, max_length=64)
    reason: str = Field(default="", max_length=500)


class EvidenceRequirementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str = Field(min_length=1, max_length=100)
    object_id: str = Field(min_length=1, max_length=160)
    requirement_code: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=2_000)
    required_status: str = Field(default="Required", min_length=1, max_length=64)
    reason: str = Field(default="", max_length=500)


class EvidenceVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual_sha256: str = Field(min_length=64, max_length=64)
    reason: str = Field(default="", max_length=500)


def _local_connection(connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if connection is None:
        raise APIError(
            status_code=500,
            code="local_database_not_configured",
            message="The local evidence database is not configured for this request.",
        )
    return connection


def _server_record(record: dict[str, object]) -> dict[str, object]:
    return {**record, "source_backend": "postgresql-evidence-registry"}


def _is_server_manage_authorized(request: Request) -> bool:
    principal = getattr(request.state, "server_principal", None)
    permissions: frozenset[str] = getattr(principal, "permissions", frozenset())
    return "evidence.manage" in permissions


def _require_evidence_manage_access(
    request: Request, current_user: EvidenceRead, connection: sqlite3.Connection | None
) -> None:
    if server_evidence_enabled(request):
        if not _is_server_manage_authorized(request):
            raise APIError(status_code=403, code="permission_denied", message="Permission denied.")
        return
    if connection is None:
        raise APIError(status_code=500, code="db_not_configured", message="Local auth database is not configured.")
    try:
        if not LocalAuthService(connection).user_has_permission(
            username=current_user.username, permission="evidence.manage"
        ):
            raise APIError(status_code=403, code="permission_denied", message="Permission denied.")
    except AuthServiceError as exc:
        raise APIError(status_code=403, code="permission_denied", message=str(exc)) from exc


@router.get("")
def list_evidence(
    request: Request,
    current_user: EvidenceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    status: str = "all",
    limit: PageLimit = 500,
    offset: PageOffset = 0,
    pagination: Literal["offset", "cursor"] = "offset",
    cursor: CursorToken = None,
) -> dict[str, object]:
    """List evidence metadata without exposing artifact bytes."""

    if cursor is not None and pagination != "cursor":
        raise APIError(
            status_code=400, code="cursor_mode_required", message="Set pagination=cursor when supplying a cursor."
        )
    if pagination == "cursor" and offset != 0:
        raise APIError(status_code=400, code="pagination_mode_conflict", message="Offset is not valid in cursor mode.")
    if server_evidence_enabled(request):
        if pagination == "cursor":
            raise APIError(
                status_code=501,
                code="cursor_pagination_backend_unavailable",
                message="Cursor pagination is not available for the PostgreSQL evidence registry yet.",
            )
        records = execute_postgres_evidence(
            request,
            lambda repository, tenant: repository.list_evidence(
                tenant_id=tenant, status=status, limit=limit, offset=offset
            ),
        )
        return {
            "evidence": [_server_record(record) for record in records],
            "pagination": {"limit": limit, "offset": offset, "returned": len(records)},
            "source": {"kind": "postgresql-evidence-registry", "server_mode": True},
        }
    try:
        records = EvidenceRegistryService(_local_connection(connection)).list_evidence(
            status="" if status.casefold() == "all" else status
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="evidence_list_failed", message=str(exc)) from exc
    if pagination == "cursor":
        page, next_cursor = _cursor_page(request, records, status=status, limit=limit, cursor=cursor)
        return {
            "evidence": page,
            "pagination": {"limit": limit, "returned": len(page), "next_cursor": next_cursor, "mode": "cursor"},
        }
    page = records[offset : offset + limit]
    return {
        "evidence": page,
        "pagination": {"limit": limit, "offset": offset, "returned": len(page)},
    }


@router.get("/coverage")
def evidence_coverage(
    request: Request,
    current_user: EvidenceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Report linked evidence coverage by governed object."""

    if server_evidence_enabled(request):
        result = execute_postgres_evidence(request, lambda repository, tenant: repository.coverage(tenant_id=tenant))
        return {"coverage": result, "source": {"kind": "postgresql-evidence-registry", "server_mode": True}}
    try:
        result = EvidenceRegistryService(_local_connection(connection)).coverage(actor_label=current_user.username)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="evidence_coverage_failed", message=str(exc)) from exc
    return {"coverage": result}


@router.get("/records/{evidence_id}")
def get_evidence(
    evidence_id: str,
    request: Request,
    current_user: EvidenceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Return evidence provenance and links; artifact bytes remain out of band."""

    if server_evidence_enabled(request):
        record = execute_postgres_evidence(
            request, lambda repository, tenant: repository.get(tenant_id=tenant, evidence_id=evidence_id)
        )
        return {
            "evidence": _server_record(record),
            "source": {"kind": "postgresql-evidence-registry", "server_mode": True},
        }
    try:
        record = EvidenceRegistryService(_local_connection(connection)).get(evidence_id)
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=404, code="evidence_record_not_found", message=str(exc)) from exc
    return {"evidence": record}


@router.get("/records/{evidence_id}/drill-down")
def get_evidence_drill_down(
    request: Request,
    evidence_id: str,
    current_user: EvidenceRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    direction: Literal["up", "down", "both"] = "both",
    max_depth: Annotated[int, Query(ge=1, le=8)] = 2,
    include_sensitive: bool = False,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 250,
    offset: Annotated[int, Query(ge=0, le=10_000_000)] = 0,
) -> dict[str, object]:
    """Return a governance-safe evidence relationship graph with optional sensitive fields."""

    if include_sensitive:
        _require_evidence_manage_access(request, current_user, connection)
    if server_evidence_enabled(request):
        result = execute_postgres_evidence(
            request,
            lambda repository, tenant: repository.drill_down(
                tenant_id=tenant,
                evidence_id=evidence_id,
                direction=direction,
                max_depth=max_depth,
                include_sensitive=include_sensitive,
                limit=limit,
                offset=offset,
                actor_id=current_user.id,
                request_id=str(getattr(request.state, "request_id", "")),
            ),
        )
        return {"drill_down": result, "source": {"kind": "postgresql-evidence-registry", "server_mode": True}}
    try:
        result = EvidenceRegistryService(_local_connection(connection)).drill_down(
            evidence_id,
            direction=direction,
            max_depth=max_depth,
            include_sensitive=include_sensitive,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise APIError(status_code=400, code="evidence_drill_down_failed", message=str(exc)) from exc
    return {"drill_down": result}


@router.post("/records")
def register_evidence(
    request: Request,
    payload: EvidenceRecordRequest,
    current_user: EvidenceManage,
) -> dict[str, object]:
    """Register provider-uploaded evidence metadata in server mode.

    Bytes are deliberately not accepted by this endpoint.  A trusted object
    storage worker must upload and checksum content before calling this
    metadata boundary.
    """

    if not server_evidence_enabled(request):
        raise APIError(
            status_code=501,
            code="evidence_registration_server_only",
            message="Evidence metadata registration is server-only; use the local CLI for local files.",
        )
    record = execute_postgres_evidence(
        request,
        lambda repository, tenant: repository.register(
            tenant_id=tenant,
            evidence_id=payload.evidence_id,
            evidence_code=payload.evidence_code,
            source_name=payload.source_name,
            checksum_sha256=payload.checksum_sha256,
            actor_id=current_user.id,
            source_reference=payload.source_reference,
            provenance_type=payload.provenance_type,
            redaction_status=payload.redaction_status,
            evidence_status=payload.evidence_status,
            storage_backend=payload.storage_backend,
            storage_tenant_id=payload.storage_tenant_id,
            storage_key=payload.storage_key,
            storage_version_id=payload.storage_version_id,
            content_type=payload.content_type,
            byte_size=payload.byte_size,
            retention_until=payload.retention_until,
            request_id=str(getattr(request.state, "request_id", "")),
            reason=payload.reason,
        ),
    )
    return {"evidence": _server_record(record), "source": {"kind": "postgresql-evidence-registry", "server_mode": True}}


@router.post("/records/{evidence_id}/links")
def link_evidence(
    evidence_id: str,
    request: Request,
    payload: EvidenceLinkRequest,
    current_user: EvidenceManage,
) -> dict[str, object]:
    """Link one evidence object to a tenant-scoped governed object."""

    if not server_evidence_enabled(request):
        raise APIError(
            status_code=501, code="evidence_link_server_only", message="Server evidence linking is not enabled."
        )
    link = execute_postgres_evidence(
        request,
        lambda repository, tenant: repository.link(
            tenant_id=tenant,
            evidence_id=evidence_id,
            object_type=payload.object_type,
            object_id=payload.object_id,
            link_type=payload.link_type,
            actor_id=current_user.id,
            request_id=str(getattr(request.state, "request_id", "")),
            reason=payload.reason,
        ),
    )
    return {"link": link, "source": {"kind": "postgresql-evidence-registry", "server_mode": True}}


@router.post("/requirements")
def save_evidence_requirement(
    request: Request,
    payload: EvidenceRequirementRequest,
    current_user: EvidenceManage,
) -> dict[str, object]:
    """Create or update one evidence requirement."""

    if not server_evidence_enabled(request):
        raise APIError(
            status_code=501,
            code="evidence_requirement_server_only",
            message="Server evidence requirements are not enabled.",
        )
    requirement = execute_postgres_evidence(
        request,
        lambda repository, tenant: repository.requirement(
            tenant_id=tenant,
            object_type=payload.object_type,
            object_id=payload.object_id,
            requirement_code=payload.requirement_code,
            description=payload.description,
            required_status=payload.required_status,
            actor_id=current_user.id,
            request_id=str(getattr(request.state, "request_id", "")),
            reason=payload.reason,
        ),
    )
    return {"requirement": requirement, "source": {"kind": "postgresql-evidence-registry", "server_mode": True}}


@router.post("/records/{evidence_id}/verify")
def verify_evidence(
    evidence_id: str,
    request: Request,
    payload: EvidenceVerifyRequest,
    current_user: EvidenceVerify,
) -> dict[str, object]:
    """Record a checksum calculated by a trusted storage verifier."""

    if not server_evidence_enabled(request):
        raise APIError(
            status_code=501, code="evidence_verify_server_only", message="Server evidence verification is not enabled."
        )
    result = execute_postgres_evidence(
        request,
        lambda repository, tenant: repository.verify_checksum(
            tenant_id=tenant,
            evidence_id=evidence_id,
            actual_sha256=payload.actual_sha256,
            actor_id=current_user.id,
            request_id=str(getattr(request.state, "request_id", "")),
            reason=payload.reason,
        ),
    )
    return {"verification": result.__dict__, "source": {"kind": "postgresql-evidence-registry", "server_mode": True}}
