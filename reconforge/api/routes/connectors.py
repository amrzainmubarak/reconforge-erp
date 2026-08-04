"""Authenticated local connector control routes."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, TypedDict, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import enforce_server_scoped_permission, get_local_db, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_writeback import execute_postgres_writeback, server_writeback_enabled
from reconforge.auth.models import LocalUser
from reconforge.connectors.writeback import (
    WritebackIntent,
    WritebackPolicy,
    WritebackStatus,
    acknowledge_writeback,
    approve_writeback,
    dispatch_writeback,
    request_compensation,
)
from reconforge.connectors.writeback_network import (
    WritebackNetworkError,
    WritebackNetworkExecutor,
    WritebackNetworkRegistration,
)
from reconforge.infrastructure.sqlite_writeback import SQLiteWritebackIntentRepository, WritebackPersistenceError

router = APIRouter(prefix="/connectors", tags=["connectors"])
WritebackProposer = Annotated[LocalUser, Depends(require_permission("connectors.writeback.propose"))]
WritebackApprover = Annotated[LocalUser, Depends(require_permission("connectors.writeback.approve"))]
WritebackDispatcher = Annotated[LocalUser, Depends(require_permission("connectors.writeback.dispatch"))]
WritebackReconciler = Annotated[LocalUser, Depends(require_permission("connectors.writeback.reconcile"))]
WritebackCompensator = Annotated[LocalUser, Depends(require_permission("connectors.writeback.compensate"))]


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


class WritebackDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=256)
    expected_version: int = Field(ge=1)


class WritebackCompensationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=2_000)
    expected_version: int = Field(ge=1)


class _MarkedDispatch(TypedDict):
    already_acknowledged: bool
    intent: WritebackIntent
    version: int
    registration: WritebackNetworkRegistration
    policy: WritebackPolicy


class _PersistedAcknowledgement(TypedDict):
    intent: WritebackIntent
    version: int


@router.post("/writeback/intents")
def propose_writeback_intent(
    request: Request,
    payload: WritebackIntent,
    current_user: WritebackProposer,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Persist one approved-scope proposal; this endpoint never dispatches network I/O."""
    if server_writeback_enabled(request):
        tenant_id, workspace_id = _require_server_scope(request, payload.tenant_id, payload.workspace_id)
        enforce_server_scoped_permission(
            request,
            permission="connectors.writeback.propose",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if payload.requested_by != current_user.id:
            raise APIError(status_code=403, code="writeback_actor_mismatch", message="Intent actor does not match the authenticated user.")

        def persist(repository: object, tenant_id: str, workspace_id: str) -> dict[str, object]:
            stored = repository.put(payload)  # type: ignore[attr-defined]
            current = repository.get(  # type: ignore[attr-defined]
                intent_id=stored.intent_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
            if current is None:
                raise APIError(status_code=500, code="writeback_intent_not_persisted", message="Intent was not persisted.")
            return _writeback_response(current["intent"], int(current["version"]), server_mode=True)

        return execute_postgres_writeback(request, persist)
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
    request: Request,
    payload: WritebackApprovalRequest,
    current_user: WritebackApprover,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Approve one persisted proposal as a distinct human checker; never dispatch."""
    if server_writeback_enabled(request):
        tenant_id, workspace_id = _require_server_scope(request, payload.tenant_id, payload.workspace_id)
        enforce_server_scoped_permission(
            request,
            permission="connectors.writeback.approve",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

        def approve(repository: object, tenant_id: str, workspace_id: str) -> dict[str, object]:
            current = repository.get(intent_id=intent_id, tenant_id=tenant_id, workspace_id=workspace_id)  # type: ignore[attr-defined]
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
                stored = repository.put(approved, expected_version=int(current["version"]))  # type: ignore[attr-defined]
            except (ValueError, WritebackPersistenceError) as exc:
                raise APIError(status_code=409, code="writeback_approval_conflict", message=str(exc)) from exc
            return _writeback_response(stored, int(current["version"]) + 1, server_mode=True)

        return execute_postgres_writeback(request, approve)
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


@router.post("/writeback/intents/{intent_id}/dispatch")
def dispatch_writeback_intent(
    intent_id: str,
    request: Request,
    payload: WritebackDispatchRequest,
    current_user: WritebackDispatcher,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Opt-in provider hand-off for an approved intent.

    The default/local profile never dispatches network traffic. Server mode
    must provide an explicitly registered ``WritebackNetworkExecutor`` and
    connector registration through application state; the intent is persisted
    as ``dispatched`` before the provider call so a timeout can be retried
    safely with the original idempotency key.
    """

    del current_user
    if not server_writeback_enabled(request):
        raise APIError(
            status_code=503,
            code="writeback_network_requires_server_profile",
            message="Network write-back requires an explicitly configured server profile.",
        )
    tenant_id, workspace_id = _require_server_scope(request, payload.tenant_id, payload.workspace_id)
    enforce_server_scoped_permission(
        request,
        permission="connectors.writeback.dispatch",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )

    def mark_dispatched(repository: object, tenant_id: str, workspace_id: str) -> _MarkedDispatch:
        current = repository.get(intent_id=intent_id, tenant_id=tenant_id, workspace_id=workspace_id)  # type: ignore[attr-defined]
        if current is None:
            raise APIError(status_code=404, code="writeback_intent_not_found", message="Write-back intent was not found.")
        intent = cast(WritebackIntent, current["intent"])
        version = int(cast(int, current["version"]))
        if version != payload.expected_version:
            raise APIError(status_code=409, code="writeback_intent_version_conflict", message="Write-back intent version is stale.")
        registration = _network_registration(request, intent.connector_id)
        policy = WritebackPolicy(
            connector_id=registration.connector_id,
            allowed_operations=registration.allowed_operations,
            feature_enabled=registration.feature_enabled,
        )
        if intent.status is WritebackStatus.APPROVED:
            try:
                dispatched = dispatch_writeback(intent, policy=policy)
                stored = repository.put(dispatched, expected_version=version)  # type: ignore[attr-defined]
            except (ValueError, WritebackPersistenceError) as exc:
                raise APIError(status_code=409, code="writeback_dispatch_conflict", message=str(exc)) from exc
            version += 1
        elif intent.status is WritebackStatus.DISPATCHED:
            dispatched = intent
            stored = intent
        elif intent.status is WritebackStatus.ACKNOWLEDGED:
            return {"already_acknowledged": True, "intent": intent, "version": version, "registration": registration, "policy": policy}
        else:
            raise APIError(status_code=409, code="writeback_dispatch_state_invalid", message="Write-back intent is not approved for dispatch.")
        return {"already_acknowledged": False, "intent": stored, "version": version, "registration": registration, "policy": policy}

    marked: _MarkedDispatch = execute_postgres_writeback(request, mark_dispatched)
    if marked["already_acknowledged"]:
        acknowledged = marked["intent"]
        return {
            "intent": acknowledged.model_dump(mode="json"),
            "version": marked["version"],
            "digest": acknowledged.digest,
            "network_dispatch": "already_acknowledged",
        }

    try:
        dispatch = request.app.state.writeback_network_executor.dispatch(
            marked["intent"],
            registration=marked["registration"],
            policy=marked["policy"],
        )
    except WritebackNetworkError as exc:
        raise APIError(status_code=502, code=str(exc), message="Provider write-back dispatch failed safely; the intent remains retryable.") from exc
    except Exception as exc:
        raise APIError(status_code=502, code="writeback_network_dispatch_failed", message="Provider write-back dispatch failed safely; the intent remains retryable.") from exc

    def persist_acknowledgement(repository: object, tenant_id: str, workspace_id: str) -> _PersistedAcknowledgement:
        current = repository.get(intent_id=intent_id, tenant_id=tenant_id, workspace_id=workspace_id)  # type: ignore[attr-defined]
        if current is None:
            raise APIError(status_code=404, code="writeback_intent_not_found", message="Write-back intent was not found.")
        current_intent = cast(WritebackIntent, current["intent"])
        if current_intent.status is WritebackStatus.ACKNOWLEDGED:
            return {"intent": current_intent, "version": int(cast(int, current["version"]))}
        try:
            stored = repository.put(dispatch.intent, expected_version=int(marked["version"]))  # type: ignore[attr-defined]
        except (ValueError, WritebackPersistenceError) as exc:
            raise APIError(status_code=409, code="writeback_acknowledgement_conflict", message=str(exc)) from exc
        return {"intent": stored, "version": int(marked["version"]) + 1}

    persisted: _PersistedAcknowledgement = execute_postgres_writeback(request, persist_acknowledgement)
    intent = persisted["intent"]
    return {
        "intent": intent.model_dump(mode="json"),
        "version": persisted["version"],
        "digest": intent.digest,
        "network_dispatch": "acknowledged",
        "request_digest": dispatch.request_digest,
        "response_digest": dispatch.response_digest,
        "attempts": dispatch.attempts,
    }


@router.post("/writeback/intents/{intent_id}/acknowledge")
def acknowledge_writeback_intent(
    intent_id: str,
    request: Request,
    payload: WritebackAcknowledgementRequest,
    current_user: WritebackReconciler,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Reconcile one provider acknowledgement to a dispatched intent."""
    if server_writeback_enabled(request):
        tenant_id, workspace_id = _require_server_scope(request, payload.tenant_id, payload.workspace_id)
        enforce_server_scoped_permission(
            request,
            permission="connectors.writeback.reconcile",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

        def acknowledge(repository: object, tenant_id: str, workspace_id: str) -> dict[str, object]:
            current = repository.get(intent_id=intent_id, tenant_id=tenant_id, workspace_id=workspace_id)  # type: ignore[attr-defined]
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
                stored = repository.put(acknowledged, expected_version=int(current["version"]))  # type: ignore[attr-defined]
            except (ValueError, WritebackPersistenceError) as exc:
                raise APIError(status_code=409, code="writeback_acknowledgement_conflict", message=str(exc)) from exc
            return _writeback_response(stored, int(current["version"]) + 1, server_mode=True)

        return execute_postgres_writeback(request, acknowledge)
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


@router.post("/writeback/intents/{intent_id}/compensate")
def request_writeback_compensation(
    intent_id: str,
    request: Request,
    payload: WritebackCompensationRequest,
    current_user: WritebackCompensator,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Record a human-governed compensation request without provider I/O.

    The request is actor-bound, optimistic-versioned, and scoped before the
    repository is touched. A replay with the same version, actor, and reason
    is idempotent; changing any of those inputs fails closed.
    """

    if server_writeback_enabled(request):
        tenant_id, workspace_id = _require_server_scope(request, payload.tenant_id, payload.workspace_id)
        enforce_server_scoped_permission(
            request,
            permission="connectors.writeback.compensate",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

        def compensate(repository: object, tenant_id: str, workspace_id: str) -> dict[str, object]:
            current = repository.get(intent_id=intent_id, tenant_id=tenant_id, workspace_id=workspace_id)  # type: ignore[attr-defined]
            if current is None:
                raise APIError(status_code=404, code="writeback_intent_not_found", message="Write-back intent was not found.")
            intent = cast(WritebackIntent, current["intent"])
            version = int(cast(int, current["version"]))
            if intent.status in {WritebackStatus.COMPENSATION_REQUESTED, WritebackStatus.COMPENSATED}:
                if payload.expected_version not in {version, version - 1}:
                    raise APIError(status_code=409, code="writeback_intent_version_conflict", message="Write-back intent version is stale.")
                if intent.compensation_reason != payload.reason or intent.compensation_requested_by not in {None, current_user.id}:
                    raise APIError(status_code=409, code="writeback_compensation_conflict", message="Compensation request is already bound to another actor or reason.")
                return _writeback_response(intent, version, server_mode=True)
            if version != payload.expected_version:
                raise APIError(status_code=409, code="writeback_intent_version_conflict", message="Write-back intent version is stale.")
            try:
                requested = request_compensation(
                    intent,
                    reason=payload.reason,
                    actor_id=current_user.id,
                    requested_at=datetime.now(UTC),
                )
                stored = repository.put(requested, expected_version=version)  # type: ignore[attr-defined]
            except (ValueError, WritebackPersistenceError) as exc:
                raise APIError(status_code=409, code="writeback_compensation_conflict", message=str(exc)) from exc
            return _writeback_response(stored, version + 1, server_mode=True)

        return execute_postgres_writeback(request, compensate)

    if connection is None:
        raise APIError(status_code=500, code="local_database_not_configured", message="Local database is not configured.")
    repository = SQLiteWritebackIntentRepository(connection)
    current = repository.get(intent_id=intent_id, tenant_id=payload.tenant_id, workspace_id=payload.workspace_id)
    if current is None:
        raise APIError(status_code=404, code="writeback_intent_not_found", message="Write-back intent was not found.")
    intent = cast(WritebackIntent, current["intent"])
    version = int(cast(int, current["version"]))
    if intent.status in {WritebackStatus.COMPENSATION_REQUESTED, WritebackStatus.COMPENSATED}:
        if payload.expected_version not in {version, version - 1}:
            raise APIError(status_code=409, code="writeback_intent_version_conflict", message="Write-back intent version is stale.")
        if intent.compensation_reason != payload.reason or intent.compensation_requested_by not in {None, current_user.id}:
            raise APIError(status_code=409, code="writeback_compensation_conflict", message="Compensation request is already bound to another actor or reason.")
        return _writeback_response(intent, version, server_mode=False)
    if version != payload.expected_version:
        raise APIError(status_code=409, code="writeback_intent_version_conflict", message="Write-back intent version is stale.")
    try:
        requested = request_compensation(
            intent,
            reason=payload.reason,
            actor_id=current_user.id,
            requested_at=datetime.now(UTC),
        )
        stored = repository.put(requested, expected_version=version)
    except (ValueError, WritebackPersistenceError) as exc:
        raise APIError(status_code=409, code="writeback_compensation_conflict", message=str(exc)) from exc
    return _writeback_response(stored, version + 1, server_mode=False)


def _require_server_scope(request: Request, tenant_id: str, workspace_id: str) -> tuple[str, str]:
    from reconforge.api.server_identity import request_execution_scope

    scope = request_execution_scope(request)
    if tenant_id != scope.tenant_id or workspace_id != scope.workspace_id:
        raise APIError(status_code=403, code="writeback_scope_mismatch", message="Intent scope does not match the authenticated request scope.")
    return scope.tenant_id, scope.workspace_id


def _writeback_response(intent: WritebackIntent, version: int, *, server_mode: bool) -> dict[str, object]:
    return {
        "intent": intent.model_dump(mode="json"),
        "version": version,
        "digest": intent.digest,
        "network_dispatch": "disabled",
        "source": {"kind": "postgresql-writeback-intent" if server_mode else "sqlite-writeback-intent", "server_mode": server_mode},
    }


def _network_registration(request: Request, connector_id: str) -> WritebackNetworkRegistration:
    registrations = getattr(request.app.state, "writeback_network_registrations", None)
    executor = getattr(request.app.state, "writeback_network_executor", None)
    if not isinstance(executor, WritebackNetworkExecutor) or not isinstance(registrations, Mapping):
        raise APIError(
            status_code=503,
            code="writeback_network_not_configured",
            message="No governed network write-back registration is configured.",
        )
    registration = registrations.get(connector_id)
    if not isinstance(registration, WritebackNetworkRegistration):
        raise APIError(
            status_code=503,
            code="writeback_connector_not_registered",
            message="The requested connector is not admitted for network write-back.",
        )
    return registration
