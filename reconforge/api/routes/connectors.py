"""Authenticated local connector control routes."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_local_db, require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
from reconforge.connectors.writeback import (
    WritebackIntent,
    WritebackPolicy,
    acknowledge_writeback,
    approve_writeback,
)
from reconforge.infrastructure.sqlite_writeback import SQLiteWritebackIntentRepository, WritebackPersistenceError

router = APIRouter(prefix="/connectors", tags=["connectors"])
WritebackProposer = Annotated[LocalUser, Depends(require_permission("connectors.writeback.propose"))]
WritebackApprover = Annotated[LocalUser, Depends(require_permission("connectors.writeback.approve"))]
WritebackReconciler = Annotated[LocalUser, Depends(require_permission("connectors.writeback.reconcile"))]


class WritebackApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assurance: str = Field(pattern=r"^(?:step_up|mfa)$")
    reason: str = Field(min_length=1, max_length=2_000)
    tenant_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=256)


class WritebackAcknowledgementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=256)
    provider_reference: str = Field(min_length=1, max_length=512)
    response_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    accepted: bool


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


@router.post("/writeback/intents/{intent_id}/approve")
def approve_writeback_intent(
    intent_id: str,
    payload: WritebackApprovalRequest,
    current_user: WritebackApprover,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Approve one persisted proposal as a distinct human checker; never dispatch."""
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="Local database is not configured.")
    repository = SQLiteWritebackIntentRepository(connection)
    current = repository.get(
        intent_id=intent_id,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
    )
    if current is None:
        raise APIError(status_code=404, code="writeback_intent_not_found", message="Write-back intent was not found.")
    intent = current["intent"]
    policy = WritebackPolicy(
        connector_id=intent.connector_id,
        allowed_operations=frozenset({intent.operation}),
        feature_enabled=intent.feature_enabled,
    )
    try:
        approved = approve_writeback(
            intent,
            policy=policy,
            actor_id=current_user.id,
            approved_at=datetime.now(UTC),
            assurance=payload.assurance,  # type: ignore[arg-type]
            reason=payload.reason,
        )
        stored = repository.put(approved, expected_version=int(current["version"]))
    except (ValueError, WritebackPersistenceError) as exc:
        raise APIError(status_code=409, code="writeback_approval_conflict", message=str(exc)) from exc
    return {
        "intent": stored.model_dump(mode="json"),
        "version": int(current["version"]) + 1,
        "digest": stored.digest,
        "network_dispatch": "disabled",
    }


@router.post("/writeback/intents/{intent_id}/acknowledge")
def acknowledge_writeback_intent(
    intent_id: str,
    payload: WritebackAcknowledgementRequest,
    current_user: WritebackReconciler,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Reconcile one provider acknowledgement to a dispatched intent."""
    del current_user
    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="Local database is not configured.")
    repository = SQLiteWritebackIntentRepository(connection)
    current = repository.get(
        intent_id=intent_id,
        tenant_id=payload.tenant_id,
        workspace_id=payload.workspace_id,
    )
    if current is None:
        raise APIError(status_code=404, code="writeback_intent_not_found", message="Write-back intent was not found.")
    intent = current["intent"]
    if payload.idempotency_key != intent.idempotency_key:
        raise APIError(status_code=409, code="writeback_idempotency_mismatch", message="Acknowledgement key does not match the intent.")
    try:
        acknowledged = acknowledge_writeback(
            intent,
            provider_reference=payload.provider_reference,
            response_digest=payload.response_digest,
            acknowledged_at=datetime.now(UTC),
            accepted=payload.accepted,
        )
        stored = repository.put(acknowledged, expected_version=int(current["version"]))
    except (ValueError, WritebackPersistenceError) as exc:
        raise APIError(status_code=409, code="writeback_acknowledgement_conflict", message=str(exc)) from exc
    return {
        "intent": stored.model_dump(mode="json"),
        "version": int(current["version"]) + 1,
        "digest": stored.digest,
        "network_dispatch": "disabled",
    }
