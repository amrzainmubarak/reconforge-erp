"""Tenant-scoped operational projections for the server and local APIs."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from reconforge.api.dependencies import (
    _server_policy_audit_sink,
    enforce_server_tenant_permission,
    get_local_db,
    require_permission,
)
from reconforge.api.errors import APIError
from reconforge.api.server_identity import (
    get_postgres_identity_factory,
    request_tenant_id,
    server_identity_enabled,
)
from reconforge.application.jobs import (
    DurableJobApplicationService,
    GovernedDurableJobApplicationService,
    JobAuthorizationError,
)
from reconforge.auth.models import LocalUser
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.auth.service import LocalAuthService
from reconforge.domain.jobs import DurableJobQueueSnapshot
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_jobs import PostgresDurableJobRepository, PostgresJobRepositoryError
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository, SQLiteJobRepositoryError
from reconforge.platform.common import ServerPrincipal, current_server_principal

router = APIRouter(prefix="/ops", tags=["operations"])

OpsRead = Annotated[LocalUser, Depends(require_permission("ops.read"))]


def _scope_query(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise APIError(status_code=400, code="invalid_scope", message=f"{field} must not be blank.")
    if len(normalized) > 160 or any(ord(character) < 33 or ord(character) > 126 for character in normalized):
        raise APIError(status_code=400, code="invalid_scope", message=f"{field} is invalid.")
    return normalized


def _snapshot_payload(snapshot: DurableJobQueueSnapshot) -> dict[str, object]:
    """Project only bounded queue health; never expose IDs, keys, or digests."""

    return {
        "tenant_id": snapshot.tenant_id,
        "workspace_id": snapshot.workspace_id,
        "organization_id": snapshot.organization_id,
        "entity_id": snapshot.entity_id,
        "counts": {
            "queued": snapshot.queued_count,
            "running": snapshot.running_count,
            "paused": snapshot.paused_count,
            "retrying": snapshot.retrying_count,
            "failed": snapshot.failed_count,
            "completed": snapshot.completed_count,
            "cancelled": snapshot.cancelled_count,
            "leased": snapshot.leased_count,
        },
        "queue_depth": snapshot.queue_depth,
        "total_count": snapshot.total_count,
        "oldest_queued_at": snapshot.oldest_queued_at,
        "oldest_running_at": snapshot.oldest_running_at,
    }


def _server_job_policy_context(
    request: Request,
    *,
    tenant_id: str,
    workspace_id: str | None,
    organization_id: str | None,
    entity_id: str | None,
) -> tuple[ServerPrincipal, PolicyEvaluationContext]:
    principal = getattr(request.state, "server_principal", None)
    if not isinstance(principal, ServerPrincipal):
        principal = current_server_principal()
    if principal is None:
        raise APIError(status_code=401, code="auth_required", message="Authentication required.")
    if principal.authorized_tenant_ids and tenant_id not in principal.authorized_tenant_ids:
        raise APIError(status_code=403, code="tenant_scope_denied", message="Tenant scope is not authorized.")
    return principal, PolicyEvaluationContext(
        user_id=principal.user.id,
        username=principal.user.username,
        user_permissions=principal.permissions,
        principal_type=principal.principal_type,
        step_up_active=principal.step_up_active,
        step_up_enforced=True,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        organization_id=organization_id,
        entity_id=entity_id,
        authorized_tenant_ids=principal.authorized_tenant_ids or frozenset({tenant_id}),
        authorized_workspace_ids=principal.authorized_workspace_ids,
        authorized_organization_ids=principal.authorized_organization_ids,
        authorized_entity_ids=principal.authorized_legal_entity_ids,
    )


@router.get("/durable-jobs/queue")
def durable_job_queue(
    request: Request,
    current_user: OpsRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    tenant_id: str | None = Query(default=None, max_length=160),
    workspace_id: str | None = Query(default=None, max_length=160),
    organization_id: str | None = Query(default=None, max_length=160),
    entity_id: str | None = Query(default=None, max_length=160),
) -> dict[str, object]:
    """Return sanitized durable-job queue health for one tenant or execution lane."""

    workspace = _scope_query(workspace_id, field="workspace_id")
    organization = _scope_query(organization_id, field="organization_id")
    entity = _scope_query(entity_id, field="entity_id")
    try:
        if server_identity_enabled(request):
            selected_tenant = request_tenant_id(request)
            enforce_server_tenant_permission(
                request,
                permission="ops.read",
                tenant_id=selected_tenant,
            )
            factory = get_postgres_identity_factory(request)
            if factory is None:
                raise APIError(
                    status_code=503,
                    code="durable_job_queue_backend_unavailable",
                    message="Server durable-job queue backend is unavailable.",
                )
            principal, policy_context = _server_job_policy_context(
                request,
                tenant_id=selected_tenant,
                workspace_id=workspace,
                organization_id=organization,
                entity_id=entity,
            )
            with PostgresTenantBoundary(factory).transaction(
                selected_tenant,
                organization_id=organization,
                workspace_id=workspace,
            ) as postgres_connection:
                snapshot = GovernedDurableJobApplicationService(
                    DurableJobApplicationService(PostgresDurableJobRepository(postgres_connection)),
                    audit_sink=_server_policy_audit_sink(request, actor_id=principal.user.id),
                ).queue_snapshot(
                    tenant_id=selected_tenant,
                    workspace_id=workspace,
                    organization_id=organization,
                    entity_id=entity,
                    actor_id=principal.user.id,
                    policy_context=policy_context,
                    required_permission="ops.read",
                    request_id=str(getattr(request.state, "request_id", "")),
                )
        else:
            if connection is None:
                raise APIError(status_code=500, code="db_not_configured", message="Database not configured.")
            if tenant_id is None or not tenant_id.strip():
                raise APIError(status_code=400, code="tenant_required", message="tenant_id is required in local mode.")
            selected_tenant = tenant_id.strip()
            local_permissions = LocalAuthService(connection).roles.user_permissions(current_user.username)
            policy_context = PolicyEvaluationContext(
                user_id=current_user.id,
                username=current_user.username,
                user_permissions=local_permissions,
                tenant_id=selected_tenant,
                workspace_id=workspace,
                organization_id=organization,
                entity_id=entity,
                authorized_tenant_ids=frozenset({selected_tenant}),
                authorized_workspace_ids=(
                    frozenset({workspace}) if workspace is not None else frozenset()
                ),
                authorized_organization_ids=(
                    frozenset({organization}) if organization is not None else frozenset()
                ),
                authorized_entity_ids=frozenset({entity}) if entity is not None else frozenset(),
            )
            snapshot = GovernedDurableJobApplicationService(
                DurableJobApplicationService(SQLiteDurableJobRepository(connection))
            ).queue_snapshot(
                tenant_id=selected_tenant,
                workspace_id=workspace,
                organization_id=organization,
                entity_id=entity,
                actor_id=current_user.id,
                policy_context=policy_context,
                required_permission="ops.read",
                request_id=str(getattr(request.state, "request_id", "")),
            )
    except APIError:
        raise
    except JobAuthorizationError as exc:
        raise APIError(
            status_code=403,
            code="durable_job_queue_scope_denied",
            message="Durable-job queue scope is not authorized.",
        ) from exc
    except (PostgresJobRepositoryError, SQLiteJobRepositoryError, ValueError) as exc:
        raise APIError(
            status_code=400,
            code="durable_job_queue_failed",
            message="Durable-job queue health could not be read.",
        ) from exc
    return {"queue": _snapshot_payload(snapshot)}


__all__ = ["router"]
