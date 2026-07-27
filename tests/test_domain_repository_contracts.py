"""Contract tests for domain repository protocols.

Verifies that repository implementations (SQLite, PostgreSQL, or mocks)
satisfy the formal repository protocol contracts.
"""

from __future__ import annotations

import sqlite3

import pytest

from reconforge.db import schema
from reconforge.domain.protocols import (
    AuditEventRepositoryProtocol,
    PeriodRepositoryProtocol,
    WorkspaceRepositoryProtocol,
)
from reconforge.domain.repositories import (
    AuditEventRepository,
    PeriodRepository,
    WorkspaceRepository,
)


@pytest.fixture
def sqlite_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(schema.INITIAL_SCHEMA_SQL)
    return connection


def test_workspace_repository_satisfies_protocol(sqlite_connection: sqlite3.Connection) -> None:
    repo = WorkspaceRepository(sqlite_connection)
    assert isinstance(repo, WorkspaceRepositoryProtocol)

    # Behavior contract test
    workspace = repo.create(name="Contract Test Organization")
    assert workspace.name == "Contract Test Organization"

    fetched = repo.get(workspace.id)
    assert fetched is not None
    assert fetched.id == workspace.id
    assert fetched.name == workspace.name

    workspaces = repo.list()
    assert len(workspaces) >= 1
    assert any(w.id == workspace.id for w in workspaces)


def test_period_repository_satisfies_protocol(sqlite_connection: sqlite3.Connection) -> None:
    ws_repo = WorkspaceRepository(sqlite_connection)
    period_repo = PeriodRepository(sqlite_connection)

    assert isinstance(period_repo, PeriodRepositoryProtocol)

    workspace = ws_repo.create(name="Period Contract Workspace")
    period = period_repo.create(
        workspace_id=workspace.id,
        name="2026-Q1",
        start_date="2026-01-01",
        end_date="2026-03-31",
    )
    assert period.name == "2026-Q1"
    assert period.status == "Open"

    fetched = period_repo.get(period.id)
    assert fetched is not None
    assert fetched.name == "2026-Q1"

    periods = period_repo.list(workspace_id=workspace.id)
    assert len(periods) == 1
    assert periods[0].id == period.id


def test_audit_event_repository_satisfies_protocol(sqlite_connection: sqlite3.Connection) -> None:
    repo = AuditEventRepository(sqlite_connection)
    assert isinstance(repo, AuditEventRepositoryProtocol)

    ref = repo.append(
        actor_label="contract_tester",
        object_type="period",
        object_id="P-100",
        action="period.lock",
        metadata={"reason": "quarterly_close"},
    )
    assert ref.actor_label == "contract_tester"
    assert ref.action == "period.lock"

    events = repo.list(limit=10)
    assert len(events) >= 1
    assert events[0].event_hash == ref.event_hash

    verification = repo.verify()
    assert verification.ok is True
    assert len(verification.issues) == 0
