"""PostgreSQL inbox adapter; every operation binds strict recipient RLS scope."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.domain.notification_inbox import (
    InboxConflictError,
    InboxError,
    InboxNotFoundError,
    InboxNotification,
    InboxPage,
    InboxPersistenceError,
    InboxPublication,
    InboxScope,
    notification_from_record,
    scope_filter_values,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository

_SCOPE = "n.tenant_id=%s AND n.workspace_id=%s AND (%s='' OR n.organization_id=%s) AND (%s='' OR n.legal_entity_id=%s)"
_READ_JOIN = "LEFT JOIN reconforge.notification_inbox_reads r ON r.tenant_id=n.tenant_id AND r.workspace_id=n.workspace_id AND r.notification_id=n.id AND r.recipient_id=n.recipient_id"


def _record(row: Any) -> InboxNotification:
    return notification_from_record(dict(row))


class PostgresNotificationInboxRepository:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def workspaces(self, tenant_id: str, actor_id: str) -> tuple[str, ...]:
        with self.connection.transaction():
            set_local_tenant_scope(self.connection, tenant_id)
            user = self.connection.execute("SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND NOT disabled", (tenant_id, actor_id)).fetchone()
            if user is None or "notifications.read" not in PostgresIdentityRepository(self.connection).user_permissions(tenant_id=tenant_id, user_id=actor_id):
                raise InboxError("Notification actor is not authorized.")
            grants = PostgresScopeAuthorityRepository(self.connection).active_for_principal(tenant_id=tenant_id, principal_type="user", principal_id=actor_id)
            return tuple(sorted(grants.workspace_ids))

    @contextmanager
    def _scope(self, scope: InboxScope, actor: str, *, publish: bool = False) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(
                    self.connection, scope.tenant_id, scope.organization_id or None,
                    workspace_id=scope.workspace_id, legal_entity_id=scope.legal_entity_id or None,
                )
                self.connection.execute("SELECT set_config('app.inbox_actor_id',%s,true)", (actor,))
                self.connection.execute("SELECT set_config('app.inbox_publish',%s,true)", ("1" if publish else "0",))
                self._authorize(scope, actor, "notifications.publish" if publish else "notifications.read")
                yield
        except (InboxError, InboxPersistenceError):
            raise
        except Exception as exc:
            raise InboxPersistenceError("Notification inbox operation failed.") from exc

    def _evidence(self, record: InboxNotification, actor: str, action: str) -> None:
        scope = record.publication.scope
        payload = {
            "schema_version": "reconforge.inbox.event.v1",
            "notification_id": record.id, "workspace_id": scope.workspace_id,
            "payload_digest": record.payload_digest,
            "published_at": record.created_at,
            "read_at": record.read_at,
        }
        event = PostgresAuditEventRepository(self.connection, scope.tenant_id).append(
            actor_label=actor, actor_user_id=actor, object_type="notification_inbox",
            object_id=record.id, action=action, metadata=payload,
        )
        self.connection.execute(
            "INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload,workspace_id,organization_id,legal_entity_id) VALUES(%s,%s,%s,%s,%s,CAST(%s AS jsonb),%s,%s,%s)",
            (scope.tenant_id, "inbox_event_" + uuid.uuid4().hex, action, "notification_inbox", record.id,
             json.dumps({**payload, "audit_event_id": event.id}), scope.workspace_id,
             scope.organization_id or None, scope.legal_entity_id or None),
        )

    def _authorize(self, scope: InboxScope, actor: str, permission: str) -> None:
        row = self.connection.execute("SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND NOT disabled FOR SHARE", (scope.tenant_id, actor)).fetchone()
        if row is None or permission not in PostgresIdentityRepository(self.connection).user_permissions(tenant_id=scope.tenant_id, user_id=actor):
            raise InboxError("Notification actor or recipient is not authorized.")
        self.connection.execute("SELECT id FROM reconforge.principal_scope_grants WHERE tenant_id=%s AND principal_type='user' AND principal_id=%s AND revoked_at IS NULL FOR SHARE", (scope.tenant_id, actor)).fetchall()
        grants = PostgresScopeAuthorityRepository(self.connection).active_for_principal(tenant_id=scope.tenant_id, principal_type="user", principal_id=actor)
        if scope.workspace_id not in grants.workspace_ids or (scope.organization_id and scope.organization_id not in grants.organization_ids) or (scope.legal_entity_id and scope.legal_entity_id not in grants.legal_entity_ids):
            raise InboxError("Notification actor or recipient is not authorized for the target scope.")
        if scope.organization_id and self.connection.execute("SELECT 1 FROM reconforge.master_data_workspace_organizations WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s", (scope.tenant_id, scope.workspace_id, scope.organization_id)).fetchone() is None:
            raise InboxError("Notification organization is unavailable in the workspace.")
        if scope.legal_entity_id and self.connection.execute("SELECT 1 FROM reconforge.legal_entities WHERE tenant_id=%s AND id=%s AND organization_id=%s", (scope.tenant_id, scope.legal_entity_id, scope.organization_id)).fetchone() is None:
            raise InboxError("Notification legal entity is unavailable in the organization.")

    def publish(self, publication: InboxPublication, publisher_id: str) -> tuple[InboxNotification, bool]:
        scope = publication.scope
        with self._scope(scope, publisher_id, publish=True):
            self._authorize(scope, publication.recipient_id, "notifications.read")
            record = InboxNotification(
                "inbox_" + uuid.uuid4().hex, publication, publisher_id,
                publication.digest(publisher_id), utc_now_text(),
            )
            row = self.connection.execute(
                "INSERT INTO reconforge.notification_inbox(tenant_id,id,workspace_id,organization_id,legal_entity_id,recipient_id,publisher_id,topic,resource_type,resource_id,idempotency_key,payload_digest,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,workspace_id,publisher_id,idempotency_key) DO NOTHING RETURNING id",
                (scope.tenant_id, record.id, scope.workspace_id, scope.organization_id, scope.legal_entity_id,
                 publication.recipient_id, publisher_id, publication.topic.value, publication.resource_type,
                 publication.resource_id, publication.idempotency_key, record.payload_digest, record.created_at),
            ).fetchone()
            if row is None:
                previous = self.connection.execute(
                    "SELECT n.*,NULL::timestamptz AS read_at FROM reconforge.notification_inbox n WHERE n.tenant_id=%s AND n.workspace_id=%s AND n.publisher_id=%s AND n.idempotency_key=%s",
                    (scope.tenant_id, scope.workspace_id, publisher_id, publication.idempotency_key),
                ).fetchone()
                if previous is None:
                    raise InboxConflictError("Notification publication key conflicts with its original scope.")
                original = _record(previous)
                if original.payload_digest != record.payload_digest:
                    raise InboxConflictError("Notification publication key conflicts with its original payload.")
                return original, False
            self._evidence(record, publisher_id, "notification.inbox_published.v1")
            return record, True

    def page(self, scope: InboxScope, recipient_id: str, *, unread_only: bool, limit: int, offset: int) -> InboxPage:
        with self._scope(scope, recipient_id):
            where = _SCOPE + " AND n.recipient_id=%s"
            params = (*scope_filter_values(scope), recipient_id)
            count = self.connection.execute(
                "SELECT COUNT(*) AS total,COALESCE(SUM(CASE WHEN r.read_at IS NULL THEN 1 ELSE 0 END),0) AS unread_count FROM reconforge.notification_inbox n " + _READ_JOIN + " WHERE " + where,  # nosec B608
                params,
            ).fetchone()
            if unread_only:
                where += " AND r.read_at IS NULL"
            rows = self.connection.execute(
                "SELECT n.*,r.read_at FROM reconforge.notification_inbox n " + _READ_JOIN + " WHERE " + where + " ORDER BY n.created_at DESC,n.id DESC LIMIT %s OFFSET %s",  # nosec B608
                (*params, limit, offset),
            ).fetchall()
            return InboxPage(
                tuple(_record(row) for row in rows),
                int(count["unread_count"] if unread_only else count["total"]), int(count["unread_count"]),
            )

    def acknowledge(self, scope: InboxScope, recipient_id: str, notification_id: str) -> InboxNotification:
        with self._scope(scope, recipient_id):
            row = self.connection.execute(
                "SELECT n.*,r.read_at FROM reconforge.notification_inbox n " + _READ_JOIN + " WHERE " + _SCOPE + " AND n.recipient_id=%s AND n.id=%s",  # nosec B608
                (*scope_filter_values(scope), recipient_id, notification_id),
            ).fetchone()
            if row is None:
                raise InboxNotFoundError("Notification was not found.")
            record = _record(row)
            changed = self.connection.execute(
                "INSERT INTO reconforge.notification_inbox_reads(tenant_id,workspace_id,notification_id,recipient_id,read_at) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING read_at",
                (scope.tenant_id, scope.workspace_id, notification_id, recipient_id, utc_now_text()),
            ).fetchone()
            read = self.connection.execute(
                "SELECT n.*,r.read_at FROM reconforge.notification_inbox n " + _READ_JOIN + " WHERE n.tenant_id=%s AND n.id=%s",  # nosec B608
                (scope.tenant_id, notification_id),
            ).fetchone()
            record = _record(read)
            if changed is not None:
                self._evidence(record, recipient_id, "notification.inbox_read.v1")
            return record
