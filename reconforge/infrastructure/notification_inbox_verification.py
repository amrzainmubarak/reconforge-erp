"""Independent retained-inbox verification for backup and restore admission."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from reconforge.domain.notification_inbox import InboxPersistenceError, notification_from_record

NOTIFICATION_INBOX_COLUMNS = (
    "id", "tenant_id", "workspace_id", "organization_id", "legal_entity_id", "recipient_id", "publisher_id",
    "topic", "resource_type", "resource_id", "idempotency_key", "payload_digest", "created_at",
)
NOTIFICATION_INBOX_READ_COLUMNS = ("tenant_id", "workspace_id", "notification_id", "recipient_id", "read_at")


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise InboxPersistenceError("Retained notification timestamp is not UTC.")
    return parsed


def verify_sqlite_inbox_storage(connection: sqlite3.Connection) -> int:
    """Verify historical identities/scope/digests and exact audit/outbox linkage.

    Revoked permissions or disabled users do not invalidate historical evidence.
    Current authorization remains the repository and request boundary's concern.
    """
    try:
        rows = connection.execute("SELECT n.*,r.read_at FROM notification_inbox n LEFT JOIN notification_inbox_reads r ON r.tenant_id=n.tenant_id AND r.workspace_id=n.workspace_id AND r.notification_id=n.id AND r.recipient_id=n.recipient_id").fetchall()
        orphans = connection.execute("SELECT COUNT(*) FROM notification_inbox_reads r WHERE NOT EXISTS(SELECT 1 FROM notification_inbox n WHERE n.tenant_id=r.tenant_id AND n.workspace_id=r.workspace_id AND n.id=r.notification_id AND n.recipient_id=r.recipient_id)").fetchone()[0]
        if orphans:
            raise InboxPersistenceError("Retained notification read evidence has no matching publication.")
        for row in rows:
            record = notification_from_record(dict(row))
            scope = record.publication.scope
            if connection.execute("SELECT 1 FROM workspaces WHERE id=?", (scope.workspace_id,)).fetchone() is None:
                raise InboxPersistenceError("Retained notification workspace is unavailable.")
            if scope.organization_id and connection.execute("SELECT 1 FROM organizations WHERE id=? AND workspace_id=?", (scope.organization_id, scope.workspace_id)).fetchone() is None:
                raise InboxPersistenceError("Retained notification organization does not match its workspace.")
            if scope.legal_entity_id and connection.execute("SELECT 1 FROM legal_entities WHERE id=? AND organization_id=?", (scope.legal_entity_id, scope.organization_id)).fetchone() is None:
                raise InboxPersistenceError("Retained notification legal entity does not match its organization.")
            for actor in (record.publisher_id, record.publication.recipient_id):
                if connection.execute("SELECT 1 FROM users WHERE id=?", (actor,)).fetchone() is None:
                    raise InboxPersistenceError("Retained notification identity is unavailable.")
            published = _utc(record.created_at)
            if record.read_at is not None and _utc(record.read_at) < published:
                raise InboxPersistenceError("Retained notification was read before publication.")
            actions = ["notification.inbox_published.v1"]
            if record.read_at is not None:
                actions.append("notification.inbox_read.v1")
            for action in actions:
                audits = connection.execute("SELECT id,actor_user_id,metadata_json FROM audit_events WHERE object_type='notification_inbox' AND object_id=? AND action=?", (record.id, action)).fetchall()
                events = connection.execute("SELECT payload_json FROM outbox_events WHERE aggregate_type='notification_inbox' AND aggregate_id=? AND event_type=?", (record.id, action)).fetchall()
                actor = record.publisher_id if action == "notification.inbox_published.v1" else record.publication.recipient_id
                expected = {"schema_version": "reconforge.inbox.event.v1", "notification_id": record.id, "workspace_id": scope.workspace_id, "payload_digest": record.payload_digest, "published_at": record.created_at, "read_at": record.read_at if action == "notification.inbox_read.v1" else None}
                if len(audits) != 1 or len(events) != 1 or audits[0]["actor_user_id"] != actor or json.loads(audits[0]["metadata_json"]) != expected or json.loads(events[0]["payload_json"]) != {**expected, "audit_event_id": audits[0]["id"]}:
                    raise InboxPersistenceError("Retained notification audit and outbox linkage does not verify.")
        return len(rows)
    except InboxPersistenceError:
        raise
    except Exception as exc:
        raise InboxPersistenceError("Retained notification storage does not verify.") from exc
