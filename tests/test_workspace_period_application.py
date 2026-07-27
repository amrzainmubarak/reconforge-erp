"""Atomic repository-port contract for workspace and first-period setup."""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from reconforge.application.workspace_periods import (
    WorkspacePeriodApplicationService,
    WorkspacePeriodValidationError,
)
from reconforge.audit.events import AuditLedgerError
from reconforge.db import schema
from reconforge.domain.protocols import DomainUnitOfWorkProtocol
from reconforge.infrastructure.sqlite_domain import SQLiteDomainUnitOfWork, SQLiteUnitOfWorkError


@pytest.fixture
def connection() -> sqlite3.Connection:
    value = sqlite3.connect(":memory:")
    value.row_factory = sqlite3.Row
    value.execute("PRAGMA foreign_keys = ON")
    value.executescript(schema.INITIAL_SCHEMA_SQL)
    return value


def _service(connection: sqlite3.Connection) -> WorkspacePeriodApplicationService:
    return WorkspacePeriodApplicationService(lambda: SQLiteDomainUnitOfWork(connection))


def test_application_service_commits_workspace_period_and_audit_atomically(
    connection: sqlite3.Connection,
) -> None:
    result = _service(connection).create(
        workspace_name="  Cairo controls  ",
        period_name=" 2026-Q3 ",
        start_date="2026-07-01",
        end_date="2026-09-30",
        actor_label=" controller ",
    )

    assert result.workspace.name == "Cairo controls"
    assert result.period.workspace_id == result.workspace.id
    assert result.period.name == "2026-Q3"
    assert [event.action for event in result.audit_events] == ["workspace.created", "period.created"]
    assert result.audit_events[1].previous_hash == result.audit_events[0].event_hash
    assert connection.execute("SELECT count(*) FROM workspaces").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM periods").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 2


def test_application_service_rolls_back_every_record_when_second_audit_append_fails(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TRIGGER reject_period_created_audit
        BEFORE INSERT ON audit_events
        WHEN NEW.action = 'period.created'
        BEGIN
            SELECT RAISE(ABORT, 'synthetic audit failure');
        END
        """
    )

    with pytest.raises(AuditLedgerError, match="Unable to append audit event"):
        _service(connection).create(
            workspace_name="Rollback workspace",
            period_name="2026-Q3",
            start_date="2026-07-01",
            end_date="2026-09-30",
            actor_label="controller",
        )

    assert connection.execute("SELECT count(*) FROM workspaces").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM periods").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 0
    state = connection.execute("SELECT last_sequence, last_event_hash FROM audit_ledger_state WHERE id = 1").fetchone()
    assert tuple(state) == (0, "0" * 64)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("workspace_name", " ", "workspace_name is required"),
        ("period_name", "\x00period", "period_name must contain printable"),
        ("start_date", "07/01/2026", "start_date must use YYYY-MM-DD"),
        ("end_date", "2026-06-30", "end_date must be on or after start_date"),
        ("actor_label", "", "actor_label is required"),
    ],
)
def test_invalid_input_fails_before_opening_a_transaction(
    connection: sqlite3.Connection,
    field: str,
    value: str,
    message: str,
) -> None:
    called = False

    def factory() -> SQLiteDomainUnitOfWork:
        nonlocal called
        called = True
        return SQLiteDomainUnitOfWork(connection)

    payload = {
        "workspace_name": "Workspace",
        "period_name": "2026-Q3",
        "start_date": "2026-07-01",
        "end_date": "2026-09-30",
        "actor_label": "controller",
    }
    payload[field] = value

    with pytest.raises(WorkspacePeriodValidationError, match=message):
        WorkspacePeriodApplicationService(factory).create(**payload)

    assert called is False
    assert connection.in_transaction is False


def test_unit_of_work_rolls_back_when_context_exits_without_commit(connection: sqlite3.Connection) -> None:
    unit_of_work = SQLiteDomainUnitOfWork(connection)
    assert isinstance(unit_of_work, DomainUnitOfWorkProtocol)

    with unit_of_work:
        unit_of_work.workspaces.create(name="Uncommitted")

    assert connection.execute("SELECT count(*) FROM workspaces").fetchone()[0] == 0


def test_unit_of_work_refuses_ambiguous_nested_transaction_ownership(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN")
    try:
        with (
            pytest.raises(SQLiteUnitOfWorkError, match="exclusive transaction ownership"),
            SQLiteDomainUnitOfWork(connection),
        ):
            pass
    finally:
        connection.rollback()


def test_application_layer_has_no_sqlite_dependency() -> None:
    source_path = Path("reconforge/application/workspace_periods.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert all(not name.startswith("sqlite3") for name in imported)
    assert all(not name.startswith("reconforge.infrastructure") for name in imported)
