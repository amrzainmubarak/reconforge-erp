"""Tenant-scoped operational projections for the server and local APIs."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from reconforge.api.dependencies import (
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
from reconforge.application.jobs import DurableJobApplicationService
from reconforge.auth.models import LocalUser
from reconforge.domain.jobs import DurableJobQueueSnapshot
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_jobs import PostgresDurableJobRepository, PostgresJobRepositoryError
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository, SQLiteJobRepositoryError

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

    del current_user
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
            with PostgresTenantBoundary(factory).transaction(
                selected_tenant,
                organization_id=organization,
                workspace_id=workspace,
            ) as postgres_connection:
                snapshot = DurableJobApplicationService(
                    PostgresDurableJobRepository(postgres_connection)
                ).queue_snapshot(
                    tenant_id=selected_tenant,
                    workspace_id=workspace,
                    organization_id=organization,
                    entity_id=entity,
                )
        else:
            if connection is None:
                raise APIError(status_code=500, code="db_not_configured", message="Database not configured.")
            if tenant_id is None or not tenant_id.strip():
                raise APIError(status_code=400, code="tenant_required", message="tenant_id is required in local mode.")
            snapshot = DurableJobApplicationService(SQLiteDurableJobRepository(connection)).queue_snapshot(
                tenant_id=tenant_id.strip(),
                workspace_id=workspace,
                organization_id=organization,
                entity_id=entity,
            )
    except APIError:
        raise
    except (PostgresJobRepositoryError, SQLiteJobRepositoryError, ValueError) as exc:
        raise APIError(
            status_code=400,
            code="durable_job_queue_failed",
            message="Durable-job queue health could not be read.",
        ) from exc
    return {"queue": _snapshot_payload(snapshot)}


__all__ = ["router"]
