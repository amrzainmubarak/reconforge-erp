from __future__ import annotations

import importlib.util
import inspect
import os
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.consolidation_close import ConsolidationCloseRepositoryProtocol
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.infrastructure.postgres_consolidation_close import (
    POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL,
    PostgresConsolidationCloseRepository,
)
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def test_postgres_consolidation_close_schema_is_tenant_scoped_and_exact() -> None:
    schema = POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL
    assert "JSONB NOT NULL" in schema
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "current_setting(''app.tenant_id'',true)" in schema
    assert "DOUBLE PRECISION" not in schema


def test_postgres_consolidation_close_migration_is_linear_and_reversible() -> None:
    path = ROOT / "alembic/versions/0055_postgres_consolidation_close.py"
    spec = importlib.util.spec_from_file_location("migration_0055", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0055_pg_consol_close"
    assert module.down_revision == "0054_pg_consol_ownership"
    assert "DROP TABLE IF EXISTS reconforge.consolidation_close_runs" in path.read_text(encoding="utf-8")


def test_postgres_adapter_exposes_the_backend_neutral_close_port() -> None:
    required = {
        name
        for name, value in vars(ConsolidationCloseRepositoryProtocol).items()
        if callable(value) and not name.startswith("__")
    }
    assert required <= set(vars(PostgresConsolidationCloseRepository))
    for name in required:
        assert callable(getattr(PostgresConsolidationCloseRepository, name))
        assert (
            inspect.signature(getattr(PostgresConsolidationCloseRepository, name)).return_annotation
            is not inspect.Signature.empty
        )


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="requires a live PostgreSQL application role",
)
def test_live_postgres_consolidation_close_is_tenant_isolated_and_replayable() -> None:
    pytest.importorskip("psycopg")
    from tests.test_sqlite_consolidation_close import _worksheet

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    tenant_a = "pgclose_a_" + uuid4().hex[:10]
    tenant_b = "pgclose_b_" + uuid4().hex[:10]
    admin = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False)).connect()
    try:
        with admin.transaction():
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.consolidation_close_periods,"
                " reconforge.consolidation_close_runs,reconforge.consolidation_close_effects,"
                " reconforge.consolidation_close_period_events TO " + app_user
            )
    finally:
        admin.close()

    connection = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False)).connect()
    try:
        repository = PostgresConsolidationCloseRepository(connection, tenant_a)
        worksheet = _worksheet()
        period = repository.create_period(
            group_code=worksheet.group_code,
            period_id=worksheet.period_id,
            reporting_currency=worksheet.reporting_currency,
            period_start_date=worksheet.period_start_date,
            period_end_date=worksheet.period_end_date,
            reporting_date=worksheet.reporting_date,
            workspace="close",
            actor_label="period-preparer",
        )
        first = repository.prepare_run(
            run_number="RUN-001", worksheet=worksheet, workspace="close", actor_label=worksheet.prepared_by
        )
        replay = repository.prepare_run(
            run_number="RUN-001", worksheet=worksheet, workspace="close", actor_label=worksheet.prepared_by
        )
        assert first["id"] == replay["id"]
        approved = repository.approve_run(
            first["id"], expected_version=1, reason="reviewed", actor_label="close-reviewer"
        )
        posted = repository.post_run(
            first["id"], expected_version=approved["row_version"], reason="posted", actor_label="close-poster"
        )
        reversal = repository.request_reversal(
            first["id"],
            expected_version=posted["row_version"],
            reason="correcting",
            actor_label="reversal-preparer",
        )
        repository.approve_reversal(
            first["id"],
            expected_version=reversal["row_version"],
            reason="approved",
            actor_label="reversal-reviewer",
        )
        locked = repository.lock_period(period["id"], expected_version=1, reason="close", actor_label="period-reviewer")
        assert locked["status"] == "Locked"
        with pytest.raises(PlatformError, match="independent"):
            repository.reopen_period(
                period["id"],
                expected_version=locked["row_version"],
                reason="same actor",
                actor_label="period-reviewer",
            )
        reopened = repository.reopen_period(
            period["id"],
            expected_version=locked["row_version"],
            reason="controlled reopen",
            actor_label="period-reopener",
        )
        assert reopened["status"] == "Open"
        assert repository.summary(workspace="close").reversed_runs == 1
        detail = repository.get_run(first["id"])
        assert detail["worksheet"]["worksheet_id"] == worksheet.worksheet_id
        events = connection.execute(
            "SELECT action,actor FROM reconforge.consolidation_close_period_events WHERE tenant_id=%s AND period_id=%s ORDER BY created_at,id",
            (tenant_a, period["id"]),
        ).fetchall()
        assert [(str(item["action"]), str(item["actor"])) for item in events] == [
            ("Locked", "period-reviewer"),
            ("Open", "period-reopener"),
        ]
        with pytest.raises(PlatformError, match="not found"):
            PostgresConsolidationCloseRepository(connection, tenant_b).get_period(period["id"])
    finally:
        connection.close()
