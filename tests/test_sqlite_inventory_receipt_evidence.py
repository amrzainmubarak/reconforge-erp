"""The SQL effect guard rejects valid evidence rows with wrong exact content."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import reconforge.infrastructure.sqlite_inventory_receipt_finance as participant_module
from reconforge.infrastructure.sqlite_finance_posting import SQLiteFinancePostingRepository
from tests.test_sqlite_finance_posting import _actor, _posting_actor
from tests.test_sqlite_inventory_receipt_posting import _fixture, _reviewed


@pytest.mark.parametrize("family", ["bundle", "finance"])
def test_effect_insert_rejects_existing_same_action_evidence_with_altered_digest(
    tmp_path: Path, monkeypatch, family: str
) -> None:
    _path, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        attempted = []
        insert = participant_module._insert

        def observed_insert(conn, table, values):
            if table == "finance_posting_effects":
                attempted.append(table)
                assert conn.execute("SELECT 1 FROM audit_events WHERE id=?", (values["audit_event_id"],)).fetchone()
                assert conn.execute("SELECT 1 FROM outbox_events WHERE id=?", (values["outbox_event_id"],)).fetchone()
            return insert(conn, table, values)

        monkeypatch.setattr(participant_module, "_insert", observed_insert)
        if family == "bundle":
            event = repository._event

            def corrupted_event(plan_id, action, actor, metadata):
                return event(plan_id, action, actor, {**metadata, "plan_digest": "0" * 64})

            monkeypatch.setattr(repository, "_event", corrupted_event)
            # Isolate the SQL guard from the Python source-content precheck.
            monkeypatch.setattr(participant_module, "verify_inventory_backing", lambda *args: None)
        else:
            evidence = SQLiteFinancePostingRepository._evidence

            def corrupted_finance(self, entry, identifier, action, actor, digest):
                return evidence(self, entry, identifier, action, actor, "0" * 64)

            monkeypatch.setattr(SQLiteFinancePostingRepository, "_evidence", corrupted_finance)
        with _actor(connection, "checker") as principal:
            before = tuple(connection.iterdump())
            with pytest.raises(sqlite3.IntegrityError, match="receipt"):
                repository.commit(
                    plan["plan_id"],
                    command_id="corrupt-exact-content",
                    expected_review_digest=review["review_digest"],
                    reason="Actual SQL exact evidence admission",
                    actor=_posting_actor(principal),
                )
            assert attempted == ["finance_posting_effects"]
            assert tuple(connection.iterdump()) == before
    finally:
        connection.close()
