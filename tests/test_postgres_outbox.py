"""Contract tests for PostgreSQL outbox delivery and worker leases."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import pytest

from reconforge.application.outbox import OutboxApplicationService, OutboxError, OutboxRepositoryProtocol
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_outbox import (
    _LIST_OUTBOX_EVENT_QUERIES,
    POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL,
    PostgresOutboxIntegrityError,
    PostgresOutboxRepository,
    PostgresOutboxValidationError,
    TenantBoundPostgresOutboxRepository,
    tenant_bound_postgres_outbox_repository,
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
    def __init__(
        self, *, attempt_count: int = 1, publishable: bool = True,
        list_status: str = "Pending", dead_lettered_at: str | None = None,
    ) -> None:
        self.attempt_count = attempt_count
        self.publishable = publishable
        self.list_status = list_status
        self.dead_lettered_at = dead_lettered_at
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
                        self.list_status,
                        self.attempt_count,
                        "2026-07-23T00:00:00Z",
                        None,
                        None,
                        None,
                        None,
                        self.dead_lettered_at,
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
    assert any("dead_lettered_at = now()" in sql for sql, _ in connection.executed)


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


def test_tenant_bound_postgres_adapter_satisfies_application_contract() -> None:
    connection = _FakeConnection()
    repository: OutboxRepositoryProtocol = tenant_bound_postgres_outbox_repository(
        connection, tenant_id="TENANT_A"
    )

    published: list[str] = []
    result = OutboxApplicationService(repository).process_once(
        publisher=lambda event: published.append(event.payload_json),
        worker_id="worker-a",
    )

    assert result.published == 1
    assert published == ['{"entry_id":"entry-a"}']
    assert all(params is None or "tenant_a" in params for sql, params in connection.executed if "outbox_events" in sql)


def test_tenant_bound_postgres_adapter_maps_status_and_safe_errors() -> None:
    connection = _FakeConnection()
    repository = TenantBoundPostgresOutboxRepository(
        PostgresOutboxRepository(connection), tenant_id="tenant_a"
    )

    events = repository.list_events(status="dead_letter")
    assert events[0].attempts == 1
    assert events[0].dead_lettered_at is None
    assert connection.executed[-1][1] == ("tenant_a", 100)

    with pytest.raises(OutboxError, match="status must be"):
        repository.list_events(status="unknown")


def test_postgres_application_pending_includes_leases_and_dead_timestamp_is_real() -> None:
    assert "status IN ('Pending', 'Claimed')" in _LIST_OUTBOX_EVENT_QUERIES["pending"]
    connection = _FakeConnection(list_status="Dead", dead_lettered_at="2026-07-23T00:10:00Z")
    repository = TenantBoundPostgresOutboxRepository(
        PostgresOutboxRepository(connection), tenant_id="tenant_a"
    )
    event = repository.list_events(status="dead_letter")[0]
    assert event.dead_lettered_at == "2026-07-23T00:10:00Z"
    assert "dead_lettered_at TIMESTAMPTZ" in POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL
    assert "dead outbox state requires exclusive transition evidence" in POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL


def test_tenant_bound_postgres_adapter_rejects_invalid_tenant_before_query() -> None:
    connection = _FakeConnection()
    with pytest.raises(PostgresOutboxValidationError):
        TenantBoundPostgresOutboxRepository(
            PostgresOutboxRepository(connection), tenant_id="tenant with spaces"
        )
    assert connection.executed == []


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service"
)
def test_live_postgres_outbox_application_claim_retry_dead_replay_publish_and_rls() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "outbox_a_" + uuid4().hex[:8]
    tenant_b = "outbox_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            admin.execute(POSTGRES_OUTBOX_APPLICATION_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        with factory.connect() as probe:
            role = probe.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        if role is None or bool(role[0]) or bool(role[1]):
            pytest.skip("requires a non-superuser, non-BYPASSRLS application role")
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            for event_id in ("evt-live-1", "evt-live-2"):
                connection.execute(
                    """INSERT INTO reconforge.outbox_events(
                    tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
                    VALUES(%s,%s,'test.created','test',%s,'{}'::jsonb)""",
                    (tenant_a, event_id, event_id),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            first = TenantBoundPostgresOutboxRepository(
                PostgresOutboxRepository(connection), tenant_id=tenant_a
            )
            claimed_a = first.claim_pending(worker_id="worker-a", limit=1, max_attempts=1, lease_seconds=60)
            assert len(claimed_a) == 1
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            second = TenantBoundPostgresOutboxRepository(
                PostgresOutboxRepository(connection), tenant_id=tenant_a
            )
            claimed_b = second.claim_pending(worker_id="worker-b", limit=1, max_attempts=2, lease_seconds=60)
            assert len(claimed_b) == 1 and claimed_b[0].id != claimed_a[0].id
            assert len(second.list_events(status="pending")) == 2
            assert second.mark_failed(
                event_id=claimed_b[0].id, worker_id="worker-b", error="synthetic failure", max_attempts=1
            )
            dead = second.list_events(status="dead_letter")
            assert len(dead) == 1 and dead[0].dead_lettered_at is not None
            second.requeue_dead_letter(event_id=dead[0].id)
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            replay = TenantBoundPostgresOutboxRepository(
                PostgresOutboxRepository(connection), tenant_id=tenant_a
            )
            replayed = replay.claim_pending(worker_id="worker-c", limit=1)
            assert len(replayed) == 1
            replay.mark_published(event_id=replayed[0].id, worker_id="worker-c")
            assert len(replay.list_events(status="published")) == 1
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            isolated = TenantBoundPostgresOutboxRepository(
                PostgresOutboxRepository(connection), tenant_id=tenant_b
            )
            assert isolated.list_events(status="all") == []
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        except psycopg.Error:
            pass
        admin.close()
