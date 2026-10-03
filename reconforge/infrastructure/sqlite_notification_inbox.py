"""SQLite inbox persistence with atomic audit/outbox and replay protection."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace

from reconforge.audit import append_audit_event
from reconforge.auth import LocalAuthService
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
from reconforge.platform.common import append_outbox_event

_SCOPE = "n.tenant_id=? AND n.workspace_id=? AND (?='' OR n.organization_id=?) AND (?='' OR n.legal_entity_id=?)"
_READ_JOIN = "LEFT JOIN notification_inbox_reads r ON r.tenant_id=n.tenant_id AND r.workspace_id=n.workspace_id AND r.notification_id=n.id AND r.recipient_id=n.recipient_id"


class SQLiteNotificationInboxRepository:
    def __init__(self, connection: sqlite3.Connection, *, tenant_id: str = "local") -> None:
        self.connection = connection
        self.tenant_id = tenant_id

    def workspaces(self, tenant_id: str, actor_id: str) -> tuple[str, ...]:
        if tenant_id != self.tenant_id:
            raise InboxError("Notification tenant is not authorized for this database.")
        user = self.connection.execute("SELECT username FROM users WHERE id=? AND disabled=0", (actor_id,)).fetchone()
        if user is None or "notifications.read" not in LocalAuthService(self.connection).roles.user_permissions(str(user["username"])):
            raise InboxError("Notification actor is not authorized.")
        return tuple(str(row["id"]) for row in self.connection.execute("SELECT id FROM workspaces ORDER BY id LIMIT 1000").fetchall())

    def _authorize(self, scope: InboxScope, actor: str, permission: str) -> None:
        if scope.tenant_id != self.tenant_id:
            raise InboxError("Notification tenant is not authorized for this database.")
        user = self.connection.execute("SELECT username FROM users WHERE id=? AND disabled=0", (actor,)).fetchone()
        if user is None or permission not in LocalAuthService(self.connection).roles.user_permissions(str(user["username"])):
            raise InboxError("Notification actor is not authorized.")
        if self.connection.execute("SELECT 1 FROM workspaces WHERE id=?", (scope.workspace_id,)).fetchone() is None:
            raise InboxError("Notification workspace is unavailable.")
        if scope.organization_id and self.connection.execute("SELECT 1 FROM organizations WHERE id=? AND workspace_id=? AND active=1", (scope.organization_id, scope.workspace_id)).fetchone() is None:
            raise InboxError("Notification organization is unavailable in the workspace.")
        if scope.legal_entity_id and self.connection.execute("SELECT 1 FROM legal_entities WHERE id=? AND organization_id=? AND active=1", (scope.legal_entity_id, scope.organization_id)).fetchone() is None:
            raise InboxError("Notification legal entity is unavailable in the organization.")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        if self.connection.in_transaction:
            raise InboxPersistenceError("Inbox writes require an idle connection.")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield
            self.connection.commit()
        except (InboxError, InboxPersistenceError):
            self.connection.rollback()
            raise
        except Exception as exc:
            self.connection.rollback()
            raise InboxPersistenceError("Notification inbox operation failed.") from exc

    def _evidence(self, record: InboxNotification, actor: str, action: str) -> None:
        payload = {
            "schema_version": "reconforge.inbox.event.v1",
            "notification_id": record.id,
            "workspace_id": record.publication.scope.workspace_id,
            "payload_digest": record.payload_digest,
            "published_at": record.created_at,
            "read_at": record.read_at,
        }
        event = append_audit_event(
            self.connection, actor_label=actor, actor_user_id=actor,
            object_type="notification_inbox", object_id=record.id, action=action, metadata=payload,
        )
        append_outbox_event(
            self.connection, event_id="inbox_event_" + uuid.uuid4().hex,
            event_type=action, aggregate_type="notification_inbox", aggregate_id=record.id,
            payload={**payload, "audit_event_id": event.id},
        )

    def publish(self, publication: InboxPublication, publisher_id: str) -> tuple[InboxNotification, bool]:
        with self._transaction():
            self._authorize(publication.scope, publisher_id, "notifications.publish")
            self._authorize(publication.scope, publication.recipient_id, "notifications.read")
            previous = self.connection.execute(
                "SELECT n.*,NULL AS read_at FROM notification_inbox n WHERE n.tenant_id=? AND n.workspace_id=? AND n.publisher_id=? AND n.idempotency_key=?",
                (publication.scope.tenant_id, publication.scope.workspace_id, publisher_id, publication.idempotency_key),
            ).fetchone()
            if previous is not None:
                record = notification_from_record(dict(previous))
                if record.payload_digest != publication.digest(publisher_id):
                    raise InboxConflictError("Notification publication key conflicts with its original payload.")
                return record, False
            record = InboxNotification(
                "inbox_" + uuid.uuid4().hex, publication, publisher_id,
                publication.digest(publisher_id), utc_now_text(),
            )
            self.connection.execute(
                "INSERT INTO notification_inbox(id,tenant_id,workspace_id,organization_id,legal_entity_id,recipient_id,publisher_id,topic,resource_type,resource_id,idempotency_key,payload_digest,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (record.id, publication.scope.tenant_id, publication.scope.workspace_id,
                 publication.scope.organization_id, publication.scope.legal_entity_id, publication.recipient_id,
                 publisher_id, publication.topic.value, publication.resource_type, publication.resource_id,
                 publication.idempotency_key, record.payload_digest, record.created_at),
            )
            self._evidence(record, publisher_id, "notification.inbox_published.v1")
            return record, True

    def page(self, scope: InboxScope, recipient_id: str, *, unread_only: bool, limit: int, offset: int) -> InboxPage:
        self._authorize(scope, recipient_id, "notifications.read")
        where = _SCOPE + " AND n.recipient_id=?"
        params = (*scope_filter_values(scope), recipient_id)
        count = self.connection.execute(
            "SELECT COUNT(*) AS total,COALESCE(SUM(CASE WHEN r.read_at IS NULL THEN 1 ELSE 0 END),0) AS unread_count FROM notification_inbox n " + _READ_JOIN + " WHERE " + where,  # nosec B608
            params,
        ).fetchone()
        if unread_only:
            where += " AND r.read_at IS NULL"
        rows = self.connection.execute(
            "SELECT n.*,r.read_at FROM notification_inbox n " + _READ_JOIN + " WHERE " + where + " ORDER BY n.created_at DESC,n.id DESC LIMIT ? OFFSET ?",  # nosec B608
            (*params, limit, offset),
        ).fetchall()
        return InboxPage(
            tuple(notification_from_record(dict(row)) for row in rows),
            int(count["unread_count"] if unread_only else count["total"]), int(count["unread_count"]),
        )

    def acknowledge(self, scope: InboxScope, recipient_id: str, notification_id: str) -> InboxNotification:
        with self._transaction():
            self._authorize(scope, recipient_id, "notifications.read")
            row = self.connection.execute(
                "SELECT n.*,r.read_at FROM notification_inbox n " + _READ_JOIN + " WHERE " + _SCOPE + " AND n.recipient_id=? AND n.id=?",  # nosec B608
                (*scope_filter_values(scope), recipient_id, notification_id),
            ).fetchone()
            if row is None:
                raise InboxNotFoundError("Notification was not found.")
            record = notification_from_record(dict(row))
            if record.read_at is None:
                read_at = utc_now_text()
                self.connection.execute(
                    "INSERT INTO notification_inbox_reads(tenant_id,workspace_id,notification_id,recipient_id,read_at) VALUES(?,?,?,?,?)",
                    (scope.tenant_id, scope.workspace_id, notification_id, recipient_id, read_at),
                )
                record = replace(record, read_at=read_at)
                self._evidence(record, recipient_id, "notification.inbox_read.v1")
            return record
