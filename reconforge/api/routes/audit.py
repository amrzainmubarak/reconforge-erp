"""Audit event routes for the local API."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from reconforge.api.dependencies import get_db, require_permission
from reconforge.api.errors import APIError
from reconforge.audit import AuditLedgerError, list_audit_events, verify_audit_events
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError

router = APIRouter(prefix="/audit", tags=["audit"])

AuditRead = Annotated[LocalUser, Depends(require_permission("audit.read"))]
AuditVerify = Annotated[LocalUser, Depends(require_permission("audit.verify"))]


@router.get("/events")
def audit_events(
    current_user: AuditRead,
    limit: int | None = None,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """List local audit events."""

    try:
        events = [event.model_dump(mode="json") for event in list_audit_events(connection, limit=limit)]
    except (DatabaseError, AuditLedgerError) as exc:
        raise APIError(status_code=400, code="audit_read_failed", message=str(exc)) from exc
    return {"events": events}


@router.get("/verify")
def audit_verify(
    current_user: AuditVerify,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict[str, object]:
    """Verify the local audit event hash chain."""

    try:
        result = verify_audit_events(connection)
    except (DatabaseError, AuditLedgerError) as exc:
        raise APIError(status_code=400, code="audit_verify_failed", message=str(exc)) from exc
    return {
        "ok": result.ok,
        "checked_events": result.checked_events,
        "head_hash": result.head_hash,
        "issues": [issue.__dict__ for issue in result.issues],
    }
