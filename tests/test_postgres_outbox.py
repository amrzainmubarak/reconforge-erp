"""Contract tests for PostgreSQL outbox delivery and worker leases."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_outbox import (
    PostgresOutboxIntegrityError,
    PostgresOutboxRepository,
    PostgresOutboxValidationError,
)
from reconforge.workers.outbox import OutboxWorkerSettings
from reconforge.workers.postgres_outbox import PostgresOutboxWorker


class _Cursor:
    def __init__(
        self,
        row: tuple[Any, ...] | None = None,
        rows: list[tuple[Any, ...]] | None = None,
        *,
        rowcount: int = 0,
    ) -> None:
        self.row = row
        self.rows = rows or []
        self.rowcount = rowcount

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _FakeConnection:
    def __init__(self, *, attempt_count: int = 1, publishable: bool = True) -> None:
        self.attempt_count = attempt_count
        self.publishable = publishable
        self.claimed = False
        self.commits = 0
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    @contextmanager
    def transaction(self) -> Any:
        yield self
        self.commits += 1

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select set_config"):
            return _Cursor()
        if normalized.startswith("with candidates"):
            if self.claimed:
                return _Cursor(rows=[])
            self.claimed = True
            return _Cursor(
                rows=[
                    (
                        "tenant_a",
                        "evt-1",
                        "ledger.entry_posted",
                        "ledger_entry",
                        "entry-a",
                        {"entry_id": "entry-a"},
                        "Claimed",
                        self.attempt_count,
                        "2026-07-23T00:00:00Z",
                        "2026-07-23T00:05:00Z",
                        "worker-a",
                        None,
                        None,
                        "2026-07-23T00:00:00Z",
                    )
                ]
            )
        if normalized.startswith("select attempt_count"):
            return _Cursor(row=(self.attempt_count,))
        if normalized.startswith("update reconforge.outbox_events"):
            return _Cursor(rowcount=0 if params and "other-worker" in params else 1)
        if normalized.startswith("select tenant_id, event_id"):
            return _Cursor(
                rows=[
                    (
                        "tenant_a",
                        "evt-1",
                        "ledger.entry_posted",
                        "ledger_entry",
                        "entry-a",
                        {"entry_id": "entry-a"},
                        "Pending",
                        self.attempt_count,
                        "2026-07-23T00:00:00Z",
                        None,
                        None,
                        None,
                        None,
                        "2026-07-23T00:00:00Z",
                    )
                ]
            )
        if normalized.startswith("select count(*) filter"):
            return _Cursor(row=(1, 0, 0, 0))
        return _Cursor()

    def close(self) -> None:
        return None


class _FakeFactory:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> _FakeConnection:
        return self.connection


def test_postgres_outbox_claim_and_transitions_are_tenant_scoped() -> None:
    assert "claimed_by TEXT" in POSTGRES_LEDGER_SCHEMA_SQL
    connection = _FakeConnection()
    repository = PostgresOutboxRepository(connection)

    events = repository.claim_pending(
        tenant_id="TENANT_A",
        worker_id="worker-a",
        limit=10,
        max_attempts=5,
        lease_seconds=60,
    )
    repository.mark_published(tenant_id="tenant_a", event_id="evt-1", worker_id="worker-a")

    assert events[0].id == "evt-1"
    assert events[0].payload == {"entry_id": "entry-a"}
    assert events[0].payload_json == '{"entry_id":"entry-a"}'
    assert connection.commits == 0
    assert any("FOR UPDATE SKIP LOCKED" in sql for sql, _ in connection.executed)
    assert any(params is not None and "tenant_a" in params for _, params in connection.executed)


def test_postgres_outbox_failure_dead_letters_at_max_attempts() -> None:
    connection = _FakeConnection(attempt_count=1)
    repository = PostgresOutboxRepository(connection)

    dead = repository.mark_failed(
        tenant_id="tenant_a",
        event_id="evt-1",
        worker_id="worker-a",
        error="publisher unavailable",
        max_attempts=1,
    )

    assert dead is True
    assert connection.commits == 0


def test_postgres_outbox_rejects_wrong_worker_and_invalid_status() -> None:
    repository = PostgresOutboxRepository(_FakeConnection())
    with pytest.raises(PostgresOutboxIntegrityError):
        repository.mark_published(tenant_id="tenant_a", event_id="evt-1", worker_id="other-worker")
    with pytest.raises(PostgresOutboxValidationError):
        repository.list_events(tenant_id="tenant_a", status="unknown")


def test_postgres_outbox_worker_publishes_with_idempotent_event_id() -> None:
    connection = _FakeConnection()
    published: list[str] = []
    worker = PostgresOutboxWorker(
        _FakeFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        publisher=lambda event: published.append(event.id),
        settings=OutboxWorkerSettings(worker_id="worker-a", poll_interval_seconds=0),
    )

    result = worker.process_once()

    assert result.claimed == 1
    assert result.published == 1
    assert result.failed == 0
    assert published == ["evt-1"]
    assert connection.commits == 2


def test_postgres_outbox_worker_records_publisher_failure() -> None:
    connection = _FakeConnection(attempt_count=1)

    def publish(_: object) -> None:
        raise RuntimeError("transport unavailable")

    worker = PostgresOutboxWorker(
        _FakeFactory(connection),
        tenant_supplier=lambda: ["tenant_a"],
        publisher=publish,
        settings=OutboxWorkerSettings(worker_id="worker-a", max_attempts=1, poll_interval_seconds=0),
    )

    result = worker.process_once()

    assert result.claimed == 1
    assert result.published == 0
    assert result.failed == 1
    assert result.dead_lettered == 1
