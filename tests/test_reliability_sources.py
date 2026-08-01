from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from reconforge.api import create_api_app
from reconforge.audit import append_audit_event
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.domain.jobs import DurableJob
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository
from reconforge.reliability import AlertState, MetricKey, evaluate_alerts
from reconforge.reliability_sources import (
    HttpReliabilityWindow,
    PostgresReliabilityCollector,
    SQLiteReliabilityCollector,
    process_memory_mib,
)


def _job() -> DurableJob:
    return DurableJob.queued(
        job_id="secret-job", idempotency_scope="scope", idempotency_key="key",
        tenant_id="secret-tenant", workspace_id="secret-workspace", entity_id="secret-entity",
        input_digest="a" * 64, config_digest="b" * 64, worker_version="worker/1",
        total_units=1, retry_ceiling=1, created_at="2026-07-30T10:00:00Z",
    )


def test_http_window_uses_exact_error_basis_points_and_nearest_rank_p95() -> None:
    window = HttpReliabilityWindow(capacity=20)
    for index in range(20):
        window.record(status_code=500 if index == 0 else 200, duration_ms=index + 1)
    assert window.measurements() == {MetricKey.HTTP_ERROR_BPS: 500, MetricKey.HTTP_P95_MS: 19}


def test_process_memory_source_returns_a_bounded_integer() -> None:
    value = process_memory_mib()
    assert isinstance(value, int) and 0 < value < 10**12


def test_reliability_cli_reports_no_data_and_strictly_fails(tmp_path: Path) -> None:
    path = tmp_path / "cli.db"
    run_migrations(path)
    runner = CliRunner()
    report = runner.invoke(app, ["ops", "reliability", "--db", str(path)])
    strict = runner.invoke(app, ["ops", "reliability", "--db", str(path), "--require-complete"])
    assert report.exit_code == 0
    assert "no_data" in report.output and "http_window" in report.output
    assert strict.exit_code == 1
    assert "tenant" not in report.output.lower()


def test_api_records_real_requests_into_explicit_reliability_window(tmp_path: Path) -> None:
    path = tmp_path / "api.db"
    run_migrations(path)
    window = HttpReliabilityWindow()
    client = TestClient(create_api_app(path, reliability_window=window))
    assert client.get("/api/v1/health").status_code == 200
    assert window.measurements()[MetricKey.HTTP_ERROR_BPS] == 0
    assert MetricKey.HTTP_P95_MS in window.measurements()


def test_collector_reads_real_queue_audit_dependencies_and_capacity(tmp_path: Path) -> None:
    path = tmp_path / "reliability.db"
    run_migrations(path)
    connection = connect(path)
    SQLiteDurableJobRepository(connection).create_or_get(_job(), actor_id="secret-actor")
    window = HttpReliabilityWindow()
    window.record(status_code=200, duration_ms=10)
    collector = SQLiteReliabilityCollector(
        connection, http_window=window, dependency_probes=(lambda: True, lambda: False), memory_mib=lambda: 64
    )
    snapshot = collector.collect(observed_at=datetime(2026, 7, 30, 10, 5, tzinfo=UTC))
    connection.close()
    assert snapshot.unavailable_sources == ()
    assert snapshot.values[MetricKey.QUEUE_DEPTH] == 1
    assert snapshot.values[MetricKey.OLDEST_JOB_AGE_SECONDS] == 300
    assert snapshot.values[MetricKey.DEPENDENCY_FAILURES] == 1
    assert snapshot.values[MetricKey.AUDIT_FAILURES] == 0
    assert snapshot.values[MetricKey.PROCESS_MEMORY_MIB] == 64
    assert "secret" not in str(snapshot).lower()


def test_unavailable_sources_become_no_data_not_false_green(tmp_path: Path) -> None:
    path = tmp_path / "unavailable.db"
    run_migrations(path)
    connection = connect(path)
    connection.execute("DROP TABLE durable_jobs")
    collector = SQLiteReliabilityCollector(connection, memory_mib=lambda: (_ for _ in ()).throw(OSError()))
    snapshot = collector.collect(observed_at=datetime.now(UTC))
    connection.close()
    alerts = {result.policy_id: result for result in evaluate_alerts(snapshot.values)}
    assert snapshot.unavailable_sources == ("durable_jobs", "http_window", "process_memory")
    assert alerts["job-backlog"].state is AlertState.NO_DATA
    assert alerts["job-age"].state is AlertState.NO_DATA
    assert alerts["process-memory"].state is AlertState.NO_DATA


def test_corrupt_audit_chain_is_a_real_critical_signal(tmp_path: Path) -> None:
    path = tmp_path / "audit.db"
    run_migrations(path)
    connection = connect(path)
    append_audit_event(
        connection, actor_label="actor", object_type="drill", object_id="synthetic", action="created"
    )
    connection.execute("DROP TRIGGER audit_events_no_update")
    connection.execute("UPDATE audit_events SET event_hash = ? WHERE sequence = 1", ("f" * 64,))
    snapshot = SQLiteReliabilityCollector(connection).collect(observed_at=datetime.now(UTC))
    connection.close()
    alerts = {result.policy_id: result for result in evaluate_alerts(snapshot.values)}
    assert snapshot.values[MetricKey.AUDIT_FAILURES] >= 1
    assert alerts["audit-integrity"].state is AlertState.CRITICAL


def test_postgres_collector_uses_scoped_aggregate_sources(monkeypatch: Any) -> None:
    class Transaction:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *args: object) -> None:
            return None

    class Cursor:
        def __init__(self, row: tuple[object, ...] = ()) -> None:
            self.row = row

        def fetchone(self) -> tuple[object, ...]:
            return self.row

    class Connection:
        closed = False

        def transaction(self) -> Transaction:
            return Transaction()

        def execute(self, sql: str, params: tuple[object, ...] = ()) -> Cursor:
            if "FROM reconforge.durable_jobs" in sql:
                assert params == ("tenant-a",)
                return Cursor((2, datetime(2026, 7, 30, 10, 0, tzinfo=UTC)))
            return Cursor()

        def close(self) -> None:
            self.closed = True

    connection = Connection()
    factory = SimpleNamespace(connect=lambda: connection)
    ledger = SimpleNamespace(verify_audit_events=lambda **kwargs: {"issues": []})
    monkeypatch.setattr("reconforge.reliability_sources.PostgresLedgerRepository", lambda value: ledger)
    snapshot = PostgresReliabilityCollector(
        factory, tenant_id="tenant-a", dependency_probes=(lambda: True,), memory_mib=lambda: 128
    ).collect(observed_at=datetime(2026, 7, 30, 10, 10, tzinfo=UTC))
    assert connection.closed is True
    assert snapshot.values[MetricKey.QUEUE_DEPTH] == 2
    assert snapshot.values[MetricKey.OLDEST_JOB_AGE_SECONDS] == 600
    assert snapshot.values[MetricKey.AUDIT_FAILURES] == 0
    assert snapshot.unavailable_sources == ("http_window",)


def test_postgres_source_failure_omits_jobs_and_audit() -> None:
    factory = SimpleNamespace(connect=lambda: (_ for _ in ()).throw(OSError("secret DSN")))
    snapshot = PostgresReliabilityCollector(factory, tenant_id="tenant-a").collect(observed_at=datetime.now(UTC))
    alerts = {result.policy_id: result for result in evaluate_alerts(snapshot.values)}
    assert {"audit_ledger", "durable_jobs", "http_window", "process_memory"} == set(snapshot.unavailable_sources)
    assert alerts["job-backlog"].state is alerts["audit-integrity"].state is AlertState.NO_DATA
    assert "secret DSN" not in str(snapshot)


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_reliability_sources_are_rls_scoped() -> None:
    app_dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", app_dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    tenant_a = "reliability_a_" + uuid4().hex[:8]
    tenant_b = "reliability_b_" + uuid4().hex[:8]
    admin = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False)).connect()
    try:
        with admin.transaction():
            admin.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s), (%s, %s)", (tenant_a, tenant_a, tenant_b, tenant_b))
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT ON reconforge.durable_jobs, reconforge.audit_events TO {app_user}")
            for tenant, job_id, created in (
                (tenant_a, "job-a", "2026-07-30T10:00:00Z"),
                (tenant_b, "job-b", "2026-07-30T09:00:00Z"),
            ):
                admin.execute(
                    """
                    INSERT INTO reconforge.durable_jobs (
                        id, schema_version, version, status, idempotency_scope, idempotency_key,
                        tenant_id, workspace_id, input_digest, config_digest, worker_version,
                        completed_units, total_units, retry_count, retry_ceiling, created_at, updated_at
                    ) VALUES (%s, 1, 1, 'queued', 'drill', %s, %s, 'workspace', %s, %s, 'worker/1', 0, 1, 0, 1, %s, %s)
                    """,
                    (job_id, job_id, tenant, "a" * 64, "b" * 64, created, created),
                )
        window = HttpReliabilityWindow()
        window.record(status_code=200, duration_ms=5)
        snapshot = PostgresReliabilityCollector(
            PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False)),
            tenant_id=tenant_a,
            http_window=window,
            dependency_probes=(lambda: True,),
            memory_mib=lambda: 256,
        ).collect(observed_at=datetime(2026, 7, 30, 10, 10, tzinfo=UTC))
        assert snapshot.unavailable_sources == ()
        assert snapshot.values[MetricKey.QUEUE_DEPTH] == 1
        assert snapshot.values[MetricKey.OLDEST_JOB_AGE_SECONDS] == 600
        assert snapshot.values[MetricKey.AUDIT_FAILURES] == 0
    finally:
        with admin.transaction():
            admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s, %s)", (tenant_a, tenant_b))
        admin.close()
