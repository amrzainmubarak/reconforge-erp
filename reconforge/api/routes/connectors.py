"""Authenticated local connector control routes."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from reconforge.api.dependencies import get_local_db, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.connectors.writeback import WritebackIntent
from reconforge.infrastructure.sqlite_writeback import SQLiteWritebackIntentRepository, WritebackPersistenceError

router = APIRouter(prefix="/connectors", tags=["connectors"])
WritebackProposer = Annotated[LocalUser, Depends(require_permission("connectors.writeback.propose"))]


@router.post("/writeback/intents")
def propose_writeback_intent(
    payload: WritebackIntent,
    current_user: WritebackProposer,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Persist one approved-scope proposal; this endpoint never dispatches network I/O."""
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="Local database is not configured.")
    if payload.requested_by != current_user.id:
        raise APIError(status_code=403, code="writeback_actor_mismatch", message="Intent actor does not match the authenticated user.")
    try:
        repository = SQLiteWritebackIntentRepository(connection)
        stored = repository.put(payload)
        current = repository.get(
            intent_id=stored.intent_id,
            tenant_id=stored.tenant_id,
            workspace_id=stored.workspace_id,
        )
    except WritebackPersistenceError as exc:
        raise APIError(status_code=409, code="writeback_intent_conflict", message=str(exc)) from exc
    if current is None:
        raise APIError(status_code=500, code="writeback_intent_not_persisted", message="Intent was not persisted.")
    return {
        "intent": current["intent"].model_dump(mode="json"),
        "version": current["version"],
        "digest": current["intent"].digest,
        "network_dispatch": "disabled",
    }
