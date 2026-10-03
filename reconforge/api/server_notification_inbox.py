"""Request-scoped server inbox operations reusing identity and hierarchy authority."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import Request

from reconforge.api.dependencies import enforce_server_scoped_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import get_postgres_identity_factory, request_execution_scope, request_tenant_id
from reconforge.application.notification_inbox import NotificationInboxService
from reconforge.domain.notification_inbox import InboxScope
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_notification_inbox import PostgresNotificationInboxRepository

T = TypeVar("T")


def server_inbox_workspaces(request: Request, actor_id: str) -> tuple[str, ...]:
    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(status_code=503, code="notification_inbox_unavailable", message="Server inbox is unavailable.")
    tenant = request_tenant_id(request)
    with PostgresTenantBoundary(factory).transaction(tenant) as connection:
        return NotificationInboxService(PostgresNotificationInboxRepository(connection)).workspaces(tenant, actor_id=actor_id)


def execute_server_inbox(
    request: Request, permission: str, operation: Callable[[NotificationInboxService, InboxScope], T]
) -> T:
    factory = get_postgres_identity_factory(request)
    if factory is None:
        raise APIError(status_code=503, code="notification_inbox_unavailable", message="Server inbox is unavailable.")
    scope = request_execution_scope(request)
    enforce_server_scoped_permission(
        request, permission=permission, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id,
        organization_id=scope.organization_id, entity_id=scope.legal_entity_id,
    )
    with PostgresTenantBoundary(factory).transaction(
        scope.tenant_id, organization_id=scope.organization_id, workspace_id=scope.workspace_id,
        legal_entity_id=scope.legal_entity_id,
    ) as connection:
        service = NotificationInboxService(PostgresNotificationInboxRepository(connection))
        return operation(
            service, InboxScope(scope.tenant_id, scope.workspace_id, scope.organization_id or "", scope.legal_entity_id or ""),
        )
