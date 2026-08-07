from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.retail_settlement import (
    run_retail_settlement_files,
    verify_retail_settlement_report,
    write_retail_settlement_report,
)
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_retail_settlement import (
    POSTGRES_RETAIL_SETTLEMENT_SCHEMA_SQL,
    PostgresRetailSettlementRepository,
)

ROOT = Path(__file__).resolve().parents[1]


def _report(tmp_path: Path) -> dict[str, object]:
    output = tmp_path / "retail-report.json"
    run = run_retail_settlement_files(
        ROOT / "examples/retail_settlement/pos_batches.json",
        ROOT / "examples/retail_settlement/settlements.json",
        currency="USD",
        tolerance="0.01",
    )
    write_retail_settlement_report(run, output)
    return verify_retail_settlement_report(output)


def test_postgres_retail_schema_is_rls_immutable_and_bounded() -> None:
    assert "JSONB NOT NULL" in POSTGRES_RETAIL_SETTLEMENT_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_RETAIL_SETTLEMENT_SCHEMA_SQL
    assert "tenant_id = current_setting('app.tenant_id', true)" in POSTGRES_RETAIL_SETTLEMENT_SCHEMA_SQL
    assert "workspace_id = current_setting('app.workspace_id', true)" in POSTGRES_RETAIL_SETTLEMENT_SCHEMA_SQL
    assert "retail settlement evidence is immutable" in POSTGRES_RETAIL_SETTLEMENT_SCHEMA_SQL
    assert "retail settlement evidence cannot be deleted" in POSTGRES_RETAIL_SETTLEMENT_SCHEMA_SQL
    assert "secret" not in POSTGRES_RETAIL_SETTLEMENT_SCHEMA_SQL.casefold()


def test_postgres_retail_migration_is_versioned_and_non_destructive() -> None:
    migration = (ROOT / "alembic/versions/0080_postgres_retail_settlement.py").read_text(encoding="utf-8")
    assert 'revision = "0080_pg_retail_settlement"' in migration
    assert 'down_revision = "0079_pg_job_cursor"' in migration
    assert "POSTGRES_RETAIL_SETTLEMENT_SCHEMA_SQL" in migration
    assert "refusing to discard retail settlement evidence" in migration
    assert "DROP TABLE IF EXISTS reconforge.retail_settlement_runs" in migration


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_retail_settlement_is_scoped_idempotent_and_append_only(tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    tenant_id = "rtlpg_" + uuid4().hex[:10]
    workspace_id = "retail-workspace"
    other_tenant = "rtlpg_other_" + uuid4().hex[:8]
    report = _report(tmp_path)
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin = admin_factory.connect()
    connection = None
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_RETAIL_SETTLEMENT_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                "GRANT SELECT, INSERT ON reconforge.retail_settlement_runs TO "
                f"{app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s), (%s, %s)",
                (tenant_id, tenant_id, other_tenant, other_tenant),
            )
        connection = app_factory.connect()
        repository = PostgresRetailSettlementRepository(connection)
        stored = repository.put_payload(
            report,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor_label="server-admin",
        )
        assert repository.put_payload(
            report,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor_label="server-admin",
        ) == stored
        assert repository.get(
            decision_digest=str(report["decision_digest"]),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        ) == stored
        assert repository.list(tenant_id=tenant_id, workspace_id=workspace_id) == (stored,)
        assert repository.get(
            decision_digest=str(report["decision_digest"]),
            tenant_id=other_tenant,
            workspace_id=workspace_id,
        ) is None
        with pytest.raises(psycopg.Error, match="immutable"), admin.transaction():
            admin.execute(
                "UPDATE reconforge.retail_settlement_runs SET prepared_by='tampered' "
                "WHERE tenant_id=%s AND workspace_id=%s",
                (tenant_id, workspace_id),
            )
    finally:
        if connection is not None:
            connection.close()
        admin.close()
