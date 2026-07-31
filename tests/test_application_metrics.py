from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.metrics import MetricsApplicationService
from reconforge.application.workspace_periods import WorkspacePeriodApplicationService
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import (
    PostgresDomainUnitOfWork,
    install_postgres_domain_schema,
)
from reconforge.infrastructure.postgres_metrics import (
    PostgresMetricsRepository,
    install_postgres_metrics_schema,
)
from reconforge.infrastructure.sqlite_metrics import SQLiteMetricsRepository


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_metrics_and_sqlite_parity(tmp_path: Path) -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")

    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "metrics_live_a_" + uuid4().hex[:8]

    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            install_postgres_metrics_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE ON reconforge.domain_workspaces, "
                f"reconforge.domain_periods, reconforge.domain_audit_ledger_state, "
                f"reconforge.domain_audit_events, reconforge.metric_definitions, "
                f"reconforge.metric_snapshots TO {app_user}"
            )
            admin.execute("INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s)", (tenant_a, tenant_a))

        # Create workspace and period
        setup = WorkspacePeriodApplicationService(
            lambda: PostgresDomainUnitOfWork(factory, tenant_a)
        ).create(
            workspace_name="Metrics", period_name="2026-08",
            start_date="2026-08-01", end_date="2026-08-31", actor_label="controller",
        )

        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresMetricsRepository(connection, tenant_a)
            service = MetricsApplicationService(repository)

            computed = service.compute(workspace="Metrics", period_name="2026-08", actor_label="controller")
            assert len(computed) == 8  # 8 standard metrics defined

            by_key = {metric["metric_key"]: metric for metric in computed}
            assert by_key["close_completion"]["value_text"] == "0.00"
            assert by_key["match_rate"]["value_text"] == "0.00"

        # SQLite parity
        sqlite_path = tmp_path / "metrics-parity.db"
        run_migrations(sqlite_path)
        sqlite_connection = connect(sqlite_path, require_exists=True)
        try:
            sqlite_connection.execute(
                "INSERT INTO workspaces (id,name,local_first_note,created_at) VALUES (?,?,?,?)",
                (setup.workspace.id, "Metrics", "", "2026-08-01T00:00:00Z"),
            )
            sqlite_connection.commit()

            sqlite_service = MetricsApplicationService(SQLiteMetricsRepository(sqlite_connection))
            sqlite_computed = sqlite_service.compute(workspace="Metrics", period_name="2026-08", actor_label="controller")
            assert len(sqlite_computed) == 8

            sqlite_by_key = {metric["metric_key"]: metric for metric in sqlite_computed}
            assert sqlite_by_key["close_completion"]["value_text"] == "0.00"
            assert sqlite_by_key["match_rate"]["value_text"] == "0.00"
        finally:
            sqlite_connection.close()

    finally:
        admin.close()
