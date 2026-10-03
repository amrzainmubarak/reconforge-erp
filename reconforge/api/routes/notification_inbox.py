"""Authenticated user inbox routes with closed envelopes and no implicit egress."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_local_db, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import server_identity_enabled
from reconforge.api.server_notification_inbox import execute_server_inbox, server_inbox_workspaces
from reconforge.application.notification_inbox import NotificationInboxService
from reconforge.auth.models import LocalUser
from reconforge.domain.notification_inbox import (
    InboxConflictError,
    InboxError,
    InboxNotFoundError,
    InboxPublication,
    InboxScope,
    InboxTopic,
)
from reconforge.infrastructure.sqlite_notification_inbox import SQLiteNotificationInboxRepository

router = APIRouter(prefix="/notifications", tags=["notifications"])
InboxRead = Annotated[LocalUser, Depends(require_permission("notifications.read"))]
InboxPublish = Annotated[LocalUser, Depends(require_permission("notifications.publish"))]
LocalDb = Annotated[sqlite3.Connection | None, Depends(get_local_db)]
T = TypeVar("T")


class PublishInboxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_id: str = Field(min_length=1, max_length=160)
    topic: InboxTopic
    resource_type: str = Field(min_length=1, max_length=160)
    resource_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=160)
    workspace: str = Field(default="default", min_length=1, max_length=160)


@router.get("/workspaces")
def inbox_workspaces(request: Request, user: InboxRead, connection: LocalDb) -> dict[str, object]:
    try:
        if server_identity_enabled(request):
            values = server_inbox_workspaces(request, user.id)
        elif connection is not None:
            tenant = request.headers.get("x-reconforge-tenant", "local") if getattr(request.app.state, "tenant_db_router", None) else "local"
            values = NotificationInboxService(SQLiteNotificationInboxRepository(connection, tenant_id=tenant)).workspaces(tenant, actor_id=user.id)
        else:
            raise InboxError("Inbox is unavailable.")
        return {"workspaces": list(values)}
    except APIError:
        raise
    except Exception as exc:
        raise APIError(status_code=503, code="notification_inbox_unavailable", message="Inbox workspaces are unavailable.") from exc


def _call(
    request: Request,
    connection: sqlite3.Connection | None,
    workspace: str,
    permission: str,
    operation: Callable[[NotificationInboxService, InboxScope], T],
) -> T:
    try:
        if server_identity_enabled(request):
            return execute_server_inbox(request, permission, operation)
        if connection is None:
            raise APIError(status_code=503, code="notification_inbox_unavailable", message="Inbox is unavailable.")
        tenant = request.headers.get("x-reconforge-tenant", "local") if getattr(request.app.state, "tenant_db_router", None) else "local"
        return operation(NotificationInboxService(SQLiteNotificationInboxRepository(connection, tenant_id=tenant)), InboxScope(tenant, workspace))
    except APIError:
        raise
    except InboxNotFoundError as exc:
        raise APIError(status_code=404, code="notification_not_found", message=str(exc)) from exc
    except InboxConflictError as exc:
        raise APIError(status_code=409, code="notification_key_conflict", message=str(exc)) from exc
    except InboxError as exc:
        raise APIError(status_code=400, code="notification_request_invalid", message=str(exc)) from exc
    except Exception as exc:
        raise APIError(status_code=503, code="notification_inbox_unavailable", message="Inbox is temporarily unavailable.") from exc


@router.get("/inbox")
def inbox_page(
    request: Request,
    user: InboxRead,
    connection: LocalDb,
    workspace: str = Query(default="default", min_length=1, max_length=160),
    unread_only: bool = False,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> dict[str, object]:
    return _call(
        request, connection, workspace, "notifications.read",
        lambda service, scope: service.page(scope, actor_id=user.id, unread_only=unread_only, limit=limit, offset=offset).public_record(),
    )


@router.post("/inbox")
def publish_inbox(
    payload: PublishInboxRequest, request: Request, user: InboxPublish, connection: LocalDb,
) -> dict[str, object]:
    def publish(service: NotificationInboxService, scope: InboxScope) -> dict[str, object]:
        if server_identity_enabled(request) and "workspace" in payload.model_fields_set and payload.workspace != scope.workspace_id:
            raise APIError(status_code=403, code="workspace_scope_denied", message="Publication workspace is not authorized.")
        record, created = service.publish(
            InboxPublication(scope, payload.recipient_id, payload.topic, payload.resource_type, payload.resource_id, payload.idempotency_key),
            actor_id=user.id,
        )
        return {"notification": record.public_record(), "created": created}

    return _call(request, connection, payload.workspace, "notifications.publish", publish)


@router.post("/inbox/{notification_id}/read")
def acknowledge_inbox(
    notification_id: str, request: Request, user: InboxRead, connection: LocalDb,
    workspace: str = Query(default="default", min_length=1, max_length=160),
) -> dict[str, object]:
    return _call(
        request, connection, workspace, "notifications.read",
        lambda service, scope: service.acknowledge(scope, actor_id=user.id, notification_id=notification_id).public_record(),
    )
