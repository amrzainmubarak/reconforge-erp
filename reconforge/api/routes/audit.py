"""Audit event routes for the local API."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from reconforge.api.dependencies import get_local_db, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_ledger import execute_postgres_ledger, server_ledger_enabled
from reconforge.audit import AuditLedgerError, list_audit_events, verify_audit_events
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError

router = APIRouter(prefix="/audit", tags=["audit"])

AuditRead = Annotated[LocalUser, Depends(require_permission("audit.read"))]
AuditVerify = Annotated[LocalUser, Depends(require_permission("audit.verify"))]


@router.get("/events")
def audit_events(
    request: Request,
    current_user: AuditRead,
    limit: int | None = None,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """List tenant-scoped audit events from the configured persistence boundary."""

    if server_ledger_enabled(request):
        events = execute_postgres_ledger(
            request,
            lambda repository, tenant: repository.list_audit_events(tenant_id=tenant, limit=limit),
        )
        return {"events": events, "source": {"kind": "postgresql-ledger-control", "server_mode": True}}

    try:
        if connection is None:
            raise APIError(
                status_code=500,
                code="local_database_not_configured",
                message="The local audit database is not configured for this request.",
            )
        events = [event.model_dump(mode="json") for event in list_audit_events(connection, limit=limit)]
    except (DatabaseError, AuditLedgerError) as exc:
        raise APIError(status_code=400, code="audit_read_failed", message=str(exc)) from exc
    return {"events": events}


@router.get("/verify")
def audit_verify(
    request: Request,
    current_user: AuditVerify,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Verify the configured tenant-scoped audit event hash chain."""

    if server_ledger_enabled(request):
        return execute_postgres_ledger(request, lambda repository, tenant: repository.verify_audit_events(tenant_id=tenant))

    try:
        if connection is None:
            raise APIError(
                status_code=500,
                code="local_database_not_configured",
                message="The local audit database is not configured for this request.",
            )
        result = verify_audit_events(connection)
    except (DatabaseError, AuditLedgerError) as exc:
        raise APIError(status_code=400, code="audit_verify_failed", message=str(exc)) from exc
    return {
        "ok": result.ok,
        "checked_events": result.checked_events,
        "head_hash": result.head_hash,
        "issues": [issue.__dict__ for issue in result.issues],
    }
