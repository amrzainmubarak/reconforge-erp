"""Persisted SQLite notification invariants and genuine concurrent publication."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

import reconforge.db.migrations as migration_module
from reconforge.application.notification_inbox import NotificationInboxService
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import DBBridgeError
from reconforge.domain.notification_inbox import (
    InboxConflictError,
    InboxError,
    InboxNotFoundError,
    InboxPersistenceError,
    InboxPublication,
    InboxScope,
    InboxTopic,
)
from reconforge.infrastructure.notification_inbox_schema import SQLITE_NOTIFICATION_INBOX_SQL
from reconforge.infrastructure.notification_inbox_verification import verify_sqlite_inbox_storage
from reconforge.infrastructure.sqlite_notification_inbox import SQLiteNotificationInboxRepository


@pytest.fixture
def inbox(tmp_path: Path):
    path = tmp_path / "inbox.db"
    run_migrations(path)
    connection = connect(path)
    for workspace in ("default", "sibling"):
        connection.execute("INSERT INTO workspaces(id,name,local_first_note,created_at) VALUES(?,?,'synthetic','2026-10-03T00:00:00Z')", (workspace, workspace))
    connection.execute("INSERT INTO organizations(id,workspace_id,name,created_at,organization_code) VALUES('ORG-A','default','Synthetic organization','2026-10-03T00:00:00Z','ORG-A')")
    for entity in ("ENT-A", "ENT-B"):
        connection.execute("INSERT INTO legal_entities(id,organization_id,entity_code,name,currency,created_at) VALUES(?,'ORG-A',?,?,'USD','2026-10-03T00:00:00Z')", (entity, entity, entity))
    connection.commit()
    auth = LocalAuthService(connection)
    publisher = auth.init_admin(username="publisher", password="Synthetic-123")
    recipient = auth.create_user(username="recipient", password="Synthetic-123", role="reviewer")
    other = auth.create_user(username="other", password="Synthetic-123", role="auditor-readonly")
    yield path, connection, publisher.id, recipient.id, other.id
    connection.close()


def _service(connection: sqlite3.Connection) -> NotificationInboxService:
    return NotificationInboxService(SQLiteNotificationInboxRepository(connection))


def _publication(recipient: str, key: str = "request-1") -> InboxPublication:
    return InboxPublication(InboxScope("local", "default"), recipient, InboxTopic.REVIEW_REQUIRED, "approval", "APR-1", key)


def _effects(connection: sqlite3.Connection) -> tuple[int, int, int, int]:
    return tuple(int(connection.execute(sql).fetchone()[0]) for sql in (
        "SELECT COUNT(*) FROM notification_inbox", "SELECT COUNT(*) FROM notification_inbox_reads",
        "SELECT COUNT(*) FROM audit_events WHERE object_type='notification_inbox'",
        "SELECT COUNT(*) FROM outbox_events WHERE aggregate_type='notification_inbox'",
    ))


def test_persisted_inbox_replay_acknowledgement_and_recipient_scope(inbox) -> None:
    path, connection, publisher, recipient, other = inbox
    service = _service(connection)
    command = _publication(recipient)
    record, created = service.publish(command, actor_id=publisher)
    assert created and service.page(command.scope, actor_id=recipient).unread_count == 1
    replay, created = service.publish(command, actor_id=publisher)
    assert not created and replay.public_record() == record.public_record()
    assert _effects(connection) == (1, 0, 1, 1)
    with pytest.raises(InboxError):
        service.page(InboxScope("foreign", "default"), actor_id=recipient)
    for scope, actor in ((command.scope, other), (InboxScope("local", "sibling"), recipient)):
        assert service.page(scope, actor_id=actor).total == 0
        with pytest.raises(InboxNotFoundError):
            service.acknowledge(scope, actor_id=actor, notification_id=record.id)
    read = service.acknowledge(command.scope, actor_id=recipient, notification_id=record.id)
    assert read.read_at and read.payload_digest == record.payload_digest
    assert service.acknowledge(command.scope, actor_id=recipient, notification_id=record.id) == read
    assert _effects(connection) == (1, 1, 2, 2)
    assert service.page(command.scope, actor_id=recipient, unread_only=True).total == 0
    with connect(path) as reopened:
        assert _service(reopened).page(command.scope, actor_id=recipient).records[0] == read


def test_changed_key_payload_and_inactive_recipient_never_create_partial_effects(inbox) -> None:
    _, connection, publisher, recipient, other = inbox
    service = _service(connection)
    command = _publication(recipient)
    service.publish(command, actor_id=publisher)
    for changed in (replace(command, resource_id="APR-2"), replace(command, recipient_id=other)):
        with pytest.raises(InboxConflictError):
            service.publish(changed, actor_id=publisher)
    connection.execute("UPDATE users SET disabled=1 WHERE id=?", (other,))
    connection.commit()
    with pytest.raises(InboxError):
        service.publish(replace(command, recipient_id=other, idempotency_key="inactive"), actor_id=publisher)
    assert _effects(connection) == (1, 0, 1, 1)


def test_notification_and_read_evidence_cannot_be_updated_or_deleted(inbox) -> None:
    _, connection, publisher, recipient, other = inbox
    service = _service(connection)
    command = _publication(recipient)
    record, _ = service.publish(command, actor_id=publisher)
    service.acknowledge(command.scope, actor_id=recipient, notification_id=record.id)
    for sql in ("UPDATE notification_inbox SET topic='job.failed'", "DELETE FROM notification_inbox", "UPDATE notification_inbox_reads SET read_at='invalid'", "DELETE FROM notification_inbox_reads"):
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(sql)
        connection.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO notification_inbox_reads VALUES(?,?,?,?,?)", ("local", "default", record.id, other, "2026-10-03T00:00:00Z"))
    connection.rollback()


def test_audit_failure_rolls_back_publication_and_acknowledgement(inbox) -> None:
    _, connection, publisher, recipient, _ = inbox
    service = _service(connection)
    command = _publication(recipient)
    connection.executescript("CREATE TRIGGER inbox_test_failure BEFORE INSERT ON audit_events WHEN NEW.object_type='notification_inbox' BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END;")
    with pytest.raises(InboxPersistenceError):
        service.publish(command, actor_id=publisher)
    assert _effects(connection) == (0, 0, 0, 0)
    connection.execute("DROP TRIGGER inbox_test_failure")
    connection.commit()
    record, _ = service.publish(command, actor_id=publisher)
    connection.executescript("CREATE TRIGGER inbox_test_failure BEFORE INSERT ON audit_events WHEN NEW.object_type='notification_inbox' BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END;")
    with pytest.raises(InboxPersistenceError):
        service.acknowledge(command.scope, actor_id=recipient, notification_id=record.id)
    assert _effects(connection) == (1, 0, 1, 1)


def test_current_disabled_state_and_permission_revocation_fail_closed(inbox) -> None:
    _, connection, publisher, recipient, _ = inbox
    service = _service(connection)
    publication = _publication(recipient)
    record, _ = service.publish(publication, actor_id=publisher)
    connection.execute("UPDATE users SET disabled=1 WHERE id=?", (recipient,))
    connection.commit()
    with pytest.raises(InboxError):
        service.page(publication.scope, actor_id=recipient)
    with pytest.raises(InboxError):
        service.acknowledge(publication.scope, actor_id=recipient, notification_id=record.id)
    assert verify_sqlite_inbox_storage(connection) == 1
    connection.execute("UPDATE users SET disabled=0 WHERE id=?", (recipient,))
    connection.execute("DELETE FROM role_permissions WHERE role_id='ROLE-reviewer' AND permission_name='notifications.read'")
    connection.commit()
    with pytest.raises(InboxError):
        service.page(publication.scope, actor_id=recipient)


def test_sqlite_restored_inbox_independently_verifies_digest_and_linkage(inbox, tmp_path: Path) -> None:
    _, connection, publisher, recipient, _ = inbox
    publication = _publication(recipient)
    record, _ = _service(connection).publish(publication, actor_id=publisher)
    _service(connection).acknowledge(publication.scope, actor_id=recipient, notification_id=record.id)
    with connect(tmp_path / "restored.db") as restored:
        connection.backup(restored)
        restored_triggers = {
            str(row["name"])
            for row in restored.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'notification_inbox%'"
            ).fetchall()
        }
        assert restored_triggers == {
            "notification_inbox_admission",
            "notification_inbox_immutable_delete",
            "notification_inbox_immutable_update",
            "notification_inbox_reads_immutable_delete",
            "notification_inbox_reads_immutable_update",
        }
        assert verify_sqlite_inbox_storage(restored) == 1
        assert _service(restored).page(publication.scope, actor_id=recipient).records[0].read_at
        restored.execute("DROP TRIGGER notification_inbox_immutable_update")
        restored.execute("UPDATE notification_inbox SET payload_digest=?", ("0" * 64,))
        restored.commit()
        with pytest.raises(InboxPersistenceError):
            verify_sqlite_inbox_storage(restored)
        restored.execute("UPDATE notification_inbox SET payload_digest=?", (record.payload_digest,))
        restored.execute("UPDATE outbox_events SET payload_json='{}' WHERE aggregate_type='notification_inbox'")
        restored.commit()
        with pytest.raises(InboxPersistenceError):
            verify_sqlite_inbox_storage(restored)


def test_registered_inbox_migration_rolls_back_every_schema_effect_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed retained-evidence migration leaves no replay-hostile partial schema."""

    path = tmp_path / "atomic-inbox.db"
    run_migrations(path, target_version=50)
    migrations = migration_module.MIGRATIONS
    broken = migration_module.Migration(
        version=51,
        name="retained_notification_inbox",
        # The duplicate table deliberately fails after the inbox tables,
        # indexes, triggers, and permission grants would otherwise exist.
        sql=SQLITE_NOTIFICATION_INBOX_SQL + "\nCREATE TABLE notification_inbox (id TEXT);",
    )
    monkeypatch.setattr(migration_module, "MIGRATIONS", (*migrations[:50], broken))

    with pytest.raises(migration_module.DatabaseError):
        migration_module.run_migrations(path)

    connection = connect(path, require_exists=True)
    try:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='notification_inbox'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='notification_inbox_reads'"
        ).fetchone() is None
        assert connection.execute("SELECT version FROM schema_migrations WHERE version=51").fetchone() is None
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 50
    finally:
        connection.close()


def test_backup_restore_preserves_and_revalidates_retained_inbox_evidence(inbox, tmp_path: Path) -> None:
    path, connection, publisher, recipient, _ = inbox
    publication = _publication(recipient)
    record, _ = _service(connection).publish(publication, actor_id=publisher)
    _service(connection).acknowledge(publication.scope, actor_id=recipient, notification_id=record.id)

    backup = create_backup(path, tmp_path / "inbox-backup")
    payload = json.loads(backup.backup_path.read_text(encoding="utf-8"))
    assert [row["id"] for row in payload["tables"]["notification_inbox"]] == [record.id]
    assert len(payload["tables"]["notification_inbox_reads"]) == 1

    restored_path = tmp_path / "inbox-restored.db"
    restore_backup(restored_path, backup.backup_path)
    with connect(restored_path, require_exists=True) as restored:
        assert verify_sqlite_inbox_storage(restored) == 1
        restored_record = _service(restored).page(publication.scope, actor_id=recipient).records[0]
        assert restored_record.id == record.id
        assert restored_record.read_at is not None


def test_backup_refuses_tampered_retained_inbox_evidence(inbox, tmp_path: Path) -> None:
    path, connection, publisher, recipient, _ = inbox
    record, _ = _service(connection).publish(_publication(recipient), actor_id=publisher)
    connection.execute("DROP TRIGGER notification_inbox_immutable_update")
    connection.execute("UPDATE notification_inbox SET payload_digest=? WHERE id=?", ("0" * 64, record.id))
    connection.commit()

    # The CLI boundary intentionally exposes only its safe generic backup
    # failure while retaining the evidence verifier as the rejection cause.
    with pytest.raises(DBBridgeError, match="Unable to create local DB backup"):
        create_backup(path, tmp_path / "tampered-inbox-backup")


def test_same_key_concurrent_publishers_have_exactly_one_business_effect(inbox) -> None:
    path, connection, publisher, recipient, _ = inbox
    command = _publication(recipient)
    def publish(_: int) -> tuple[str, bool]:
        independent = connect(path)
        try:
            record, created = _service(independent).publish(command, actor_id=publisher)
            return record.id, created
        finally:
            independent.close()
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(publish, range(16)))
    assert len({item[0] for item in results}) == 1
    assert sum(item[1] for item in results) == 1
    assert _effects(connection) == (1, 0, 1, 1)


def test_child_scope_and_pagination_are_enforced(inbox) -> None:
    _, connection, publisher, recipient, _ = inbox
    service = _service(connection)
    for number in range(5):
        service.publish(replace(_publication(recipient, f"key-{number}"), scope=InboxScope("local", "default", "ORG-A", "ENT-A")), actor_id=publisher)
    assert service.page(InboxScope("local", "default", "ORG-A", "ENT-B"), actor_id=recipient).total == 0
    first = service.page(InboxScope("local", "default"), actor_id=recipient, limit=2)
    second = service.page(InboxScope("local", "default"), actor_id=recipient, limit=2, offset=2)
    assert first.total == second.total == 5
    assert not {record.id for record in first.records} & {record.id for record in second.records}
    for limit, offset in ((0, 0), (201, 0), (1, -1), (True, 0), (1, 100_001)):
        with pytest.raises(InboxError):
            service.page(InboxScope("local", "default"), actor_id=recipient, limit=limit, offset=offset)


@pytest.mark.parametrize("unsafe", ["", "../../etc/passwd", "https://example.com", "unsafe\nidentifier", "x" * 161])
def test_closed_envelopes_reject_urls_paths_controls_and_unbounded_values(unsafe: str) -> None:
    with pytest.raises(InboxError):
        _publication(unsafe)
