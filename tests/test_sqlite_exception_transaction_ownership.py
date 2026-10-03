"""Caller-owned exception evidence must share its aggregate's transaction."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from reconforge.audit import verify_audit_events
from reconforge.db import connect, run_migrations
from reconforge.domain.repositories import WorkspaceRepository
from reconforge.platform.common import PlatformError
from reconforge.platform.exceptions import ExceptionQueueService
from reconforge.platform.payables import PayablesService, SupplierInvoiceLineInput
from tests.test_payables import _prepare_purchase_order


@pytest.fixture
def database(tmp_path: Path) -> Iterator[tuple[Path, sqlite3.Connection]]:
    path = tmp_path / "exception-ownership.db"
    run_migrations(path)
    connection = connect(path, require_exists=True)
    try:
        yield path, connection
    finally:
        connection.close()


def _state(connection: sqlite3.Connection) -> dict[str, Any]:
    tables = (
        "workspaces", "exceptions_queue", "ap_supplier_invoices", "ap_three_way_matches",
        "audit_events", "audit_ledger_state", "outbox_events",
    )
    return {
        table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in tables
    }


def _persisted_state(path: Path) -> dict[str, Any]:
    reader = connect(path, require_exists=True)
    try:
        return _state(reader)
    finally:
        reader.close()


def _submitted_invoice(service: PayablesService, *, exception: bool) -> dict[str, Any]:
    order = _prepare_purchase_order(service)
    order = service.submit_purchase_order(str(order["id"]), expected_version=1)
    order = service.approve_purchase_order(str(order["id"]), expected_version=2, actor_label="checker")
    line_id = str(order["lines"][0]["id"])
    service.post_receipt(
        receipt_number="SYN-RECEIPT", purchase_order_id=str(order["id"]),
        receipt_date="2026-07-03", quantities={line_id: "3"},
    )
    price_minor = 1_100 if exception else 1_000
    invoice = service.create_supplier_invoice(
        invoice_number="SYN-INVOICE", supplier_code="SUP-001", invoice_date="2026-07-04",
        currency_code="USD", total_minor=price_minor * 3, purchase_order_id=str(order["id"]),
        lines=[SupplierInvoiceLineInput(
            purchase_order_line_id=line_id, invoiced_quantity="3",
            unit_price_minor=price_minor, line_total_minor=price_minor * 3,
        )],
    )
    return service.submit_supplier_invoice(str(invoice["id"]), expected_version=1)


@pytest.mark.parametrize("exception", [False, True], ids=["passed-match", "exception-match"])
@pytest.mark.parametrize("failure_at", [None, "audit", "outbox"], ids=["success", "late-audit", "late-outbox"])
def test_ap_matching_commits_business_exception_and_evidence_as_one_unit(
    database: tuple[Path, sqlite3.Connection], exception: bool, failure_at: str | None,
) -> None:
    path, connection = database
    service = PayablesService(connection)
    invoice = _submitted_invoice(service, exception=exception)
    before = _persisted_state(path)
    if failure_at is not None:
        if failure_at == "audit":
            connection.execute(
                """CREATE TRIGGER reject_late_ap_evidence BEFORE INSERT ON audit_events
                   WHEN NEW.action = 'ap_three_way_match_completed'
                   BEGIN SELECT RAISE(ABORT, 'synthetic late AP audit failure'); END"""
            )
        else:
            connection.execute(
                """CREATE TRIGGER reject_late_ap_evidence BEFORE INSERT ON outbox_events
                   WHEN NEW.event_type = 'ap.three_way_match.completed'
                   BEGIN SELECT RAISE(ABORT, 'synthetic late AP outbox failure'); END"""
            )
        with pytest.raises(PlatformError, match="Unable"):
            service.run_three_way_match(str(invoice["id"]))
        assert connection.in_transaction is False
        assert _state(connection) == before
        assert _persisted_state(path) == before
        connection.execute("DROP TRIGGER reject_late_ap_evidence")

    # A manual retry after removing the injected fault has one business effect.
    result = service.run_three_way_match(str(invoice["id"]))
    assert result.status == ("Exception" if exception else "Passed")
    assert connection.in_transaction is False
    reader = connect(path, require_exists=True)
    try:
        saved = reader.execute("SELECT status, row_version FROM ap_supplier_invoices WHERE id=?", (invoice["id"],)).fetchone()
        assert tuple(saved) == ("Exception" if exception else "Matched", 3)
        assert reader.execute("SELECT COUNT(*) FROM ap_three_way_matches").fetchone()[0] == 1
        assert reader.execute("SELECT COUNT(*) FROM exceptions_queue").fetchone()[0] == int(exception)
        assert reader.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='ap_three_way_match_completed'"
        ).fetchone()[0] == 1
        assert reader.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action='exception_saved'"
        ).fetchone()[0] == int(exception)
        assert reader.execute(
            "SELECT COUNT(*) FROM outbox_events WHERE event_type='ap.three_way_match.completed'"
        ).fetchone()[0] == 1
        assert verify_audit_events(reader).ok
    finally:
        reader.close()


def _create_exception(queue: ExceptionQueueService) -> dict[str, Any]:
    return queue.upsert_exception(
        source_type="synthetic", source_id="SYN-EXCEPTION", description="Synthetic ownership regression",
    )


def test_default_exception_mutation_remains_durably_committed(
    database: tuple[Path, sqlite3.Connection],
) -> None:
    path, connection = database
    record = _create_exception(ExceptionQueueService(connection))
    assert connection.in_transaction is False
    reader = connect(path, require_exists=True)
    try:
        assert reader.execute("SELECT id FROM exceptions_queue").fetchone()[0] == record["id"]
        assert reader.execute("SELECT action FROM audit_events").fetchone()[0] == "exception_saved"
        assert verify_audit_events(reader).ok
    finally:
        reader.close()


@pytest.mark.parametrize("commit", [False, True], ids=["caller-rollback", "caller-commit"])
def test_non_autocommit_exception_waits_for_its_caller_transaction(
    database: tuple[Path, sqlite3.Connection], commit: bool,
) -> None:
    path, connection = database
    before = _persisted_state(path)
    connection.execute("BEGIN IMMEDIATE")
    WorkspaceRepository(connection, autocommit=False).create(name="Caller pending work")
    _create_exception(ExceptionQueueService(connection, autocommit=False))
    assert connection.in_transaction is True
    assert _persisted_state(path) == before
    if commit:
        connection.commit()
        saved = _persisted_state(path)
        assert len(saved["workspaces"]) == 2
        assert len(saved["exceptions_queue"]) == 1
        assert len(saved["audit_events"]) == 1
        assert verify_audit_events(connection).ok
    else:
        connection.rollback()
        assert _persisted_state(path) == before


def test_non_autocommit_audit_failure_leaves_rollback_to_caller(
    database: tuple[Path, sqlite3.Connection],
) -> None:
    path, connection = database
    before = _persisted_state(path)
    connection.execute(
        """CREATE TRIGGER reject_exception_audit BEFORE INSERT ON audit_events
           WHEN NEW.action = 'exception_saved'
           BEGIN SELECT RAISE(ABORT, 'synthetic exception audit failure'); END"""
    )
    connection.execute("BEGIN IMMEDIATE")
    WorkspaceRepository(connection, autocommit=False).create(name="Caller pending work")
    with pytest.raises(PlatformError, match="audit evidence"):
        _create_exception(ExceptionQueueService(connection, autocommit=False))
    assert connection.in_transaction is True
    assert connection.execute("SELECT COUNT(*) FROM exceptions_queue").fetchone()[0] == 1
    assert _persisted_state(path) == before
    connection.rollback()
    assert _persisted_state(path) == before


@pytest.mark.parametrize("operation", ["insert", "update"])
def test_non_autocommit_sql_failure_does_not_discard_caller_work(
    database: tuple[Path, sqlite3.Connection], operation: str,
) -> None:
    path, connection = database
    if operation == "update":
        record = _create_exception(ExceptionQueueService(connection))
    before = _persisted_state(path)
    trigger_operation = "INSERT" if operation == "insert" else "UPDATE"
    connection.execute(
        f"CREATE TRIGGER reject_exception_write BEFORE {trigger_operation} ON exceptions_queue "
        "BEGIN SELECT RAISE(ABORT, 'synthetic exception write failure'); END"
    )
    connection.execute("BEGIN IMMEDIATE")
    WorkspaceRepository(connection, autocommit=False).create(name="Caller pending work")
    queue = ExceptionQueueService(connection, autocommit=False)
    with pytest.raises(PlatformError, match="Unable to (save|update) exception queue record"):
        if operation == "insert":
            _create_exception(queue)
        else:
            queue.assign(str(record["id"]), owner="synthetic-reviewer")
    assert connection.in_transaction is True
    assert connection.execute("SELECT COUNT(*) FROM workspaces WHERE name='Caller pending work'").fetchone()[0] == 1
    assert _persisted_state(path) == before
    connection.rollback()
    assert _persisted_state(path) == before


def test_non_autocommit_empty_bulk_does_not_open_and_commit_an_audit_transaction(
    database: tuple[Path, sqlite3.Connection],
) -> None:
    path, connection = database
    before = _persisted_state(path)
    with pytest.raises(PlatformError, match="active transaction"):
        ExceptionQueueService(connection, autocommit=False).bulk_update([], status="Open")
    assert connection.in_transaction is False
    assert _persisted_state(path) == before
