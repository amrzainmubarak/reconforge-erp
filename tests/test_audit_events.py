from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reconforge.audit import AuditLedgerError, append_audit_event, list_audit_events, verify_audit_events
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.io import persisted as persisted_module
from reconforge.io.structured import StructuredDocumentPolicy

runner = CliRunner()


def test_audit_events_append_and_verify_hash_chain(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        first = append_audit_event(
            connection,
            actor_label="system",
            object_type="workspace",
            object_id="WS-1",
            action="created",
            metadata={"source": "test"},
        )
        second = append_audit_event(
            connection,
            actor_label="controller",
            object_type="period",
            object_id="PER-1",
            action="opened",
        )
        verification = verify_audit_events(connection)
        events = list_audit_events(connection)
    finally:
        connection.close()

    assert first.sequence == 1
    assert second.sequence == 2
    assert second.previous_hash == first.event_hash
    assert verification.ok
    assert verification.checked_events == 2
    assert [event.action for event in events] == ["created", "opened"]


def test_audit_events_are_append_only_for_normal_sql_updates(tmp_path: Path) -> None:
    db_path = tmp_path / "append_only.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        append_audit_event(
            connection,
            actor_label="system",
            object_type="workspace",
            object_id="WS-1",
            action="created",
        )
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute("UPDATE audit_events SET action = 'tampered' WHERE sequence = 1")
    finally:
        connection.close()


def test_audit_verify_detects_modified_event_after_tamper(tmp_path: Path) -> None:
    db_path = tmp_path / "tamper.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        append_audit_event(
            connection,
            actor_label="system",
            object_type="workspace",
            object_id="WS-1",
            action="created",
        )
        connection.execute("DROP TRIGGER audit_events_no_update")
        connection.execute("UPDATE audit_events SET action = 'tampered' WHERE sequence = 1")
        connection.commit()

        verification = verify_audit_events(connection)
    finally:
        connection.close()

    assert not verification.ok
    assert any("hash does not match" in issue.message for issue in verification.issues)


def test_audit_verify_detects_deleted_event_after_tamper(tmp_path: Path) -> None:
    db_path = tmp_path / "delete_tamper.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        append_audit_event(
            connection,
            actor_label="system",
            object_type="workspace",
            object_id="WS-1",
            action="created",
        )
        connection.execute("DROP TRIGGER audit_events_no_delete")
        connection.execute("DELETE FROM audit_events WHERE sequence = 1")
        connection.commit()

        verification = verify_audit_events(connection)
    finally:
        connection.close()

    assert not verification.ok
    assert any("ledger state" in issue.message for issue in verification.issues)


def test_audit_cli_list_and_verify(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_cli.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        append_audit_event(
            connection,
            actor_label="system",
            object_type="workspace",
            object_id="WS-1",
            action="created",
        )
    finally:
        connection.close()

    listed = runner.invoke(app, ["audit", "list", "--db", str(db_path)])
    verified = runner.invoke(app, ["audit", "verify", "--db", str(db_path)])

    assert listed.exit_code == 0
    assert "Audit Events" in listed.output
    assert verified.exit_code == 0
    assert "Audit ledger verified" in verified.output
    assert "Traceback" not in listed.output + verified.output


def test_audit_cli_verify_reports_tamper_without_traceback(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_cli_tamper.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        append_audit_event(
            connection,
            actor_label="system",
            object_type="workspace",
            object_id="WS-1",
            action="created",
        )
        connection.execute("DROP TRIGGER audit_events_no_update")
        connection.execute("UPDATE audit_events SET actor_label = 'tampered' WHERE sequence = 1")
        connection.commit()
    finally:
        connection.close()

    result = runner.invoke(app, ["audit", "verify", "--db", str(db_path)])

    assert result.exit_code == 1
    assert "Audit ledger verification failed" in result.output
    assert "Traceback" not in result.output


def test_audit_metadata_must_be_json_serializable(tmp_path: Path) -> None:
    db_path = tmp_path / "bad_metadata.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        with pytest.raises(AuditLedgerError, match="JSON-serializable"):
            append_audit_event(
                connection,
                actor_label="system",
                object_type="workspace",
                object_id="WS-1",
                action="created",
                metadata={"bad": {1, 2, 3}},
            )
    finally:
        connection.close()


def test_audit_metadata_corruption_is_visible_to_list_and_verification(tmp_path: Path) -> None:
    db_path = tmp_path / "corrupt_metadata.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        append_audit_event(
            connection,
            actor_label="system",
            object_type="workspace",
            object_id="WS-1",
            action="created",
            metadata={"source": "test"},
        )
        connection.execute("DROP TRIGGER audit_events_no_update")
        connection.execute(
            "UPDATE audit_events SET metadata_json = ? WHERE sequence = 1",
            ('{"source":"first","source":"second"}',),
        )
        connection.commit()

        with pytest.raises(AuditLedgerError, match="Stored audit event metadata is invalid"):
            list_audit_events(connection)
        verification = verify_audit_events(connection)
    finally:
        connection.close()

    assert verification.ok is False
    assert any(issue.message == "Audit event metadata is invalid." for issue in verification.issues)
    assert any("hash does not match" in issue.message for issue in verification.issues)


def test_oversized_audit_metadata_rejects_before_transaction_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "oversized_metadata.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    monkeypatch.setattr(
        persisted_module,
        "AUDIT_METADATA_JSON_POLICY",
        StructuredDocumentPolicy(max_file_bytes=16),
    )
    try:
        before = connection.total_changes
        with pytest.raises(AuditLedgerError, match="JSON-serializable"):
            append_audit_event(
                connection,
                actor_label="system",
                object_type="workspace",
                object_id="WS-1",
                action="created",
                metadata={"value": "exceeds-budget"},
            )
        count = connection.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"]
    finally:
        connection.close()

    assert count == 0
    assert before == 0
