from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.manufacturing_cost_control import (
    run_manufacturing_cost_control_files,
    verify_manufacturing_report,
    write_manufacturing_report,
)
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_manufacturing_cost_control import (
    POSTGRES_MANUFACTURING_COST_CONTROL_SCHEMA_SQL,
    PostgresManufacturingCostControlRepository,
)

ROOT = Path(__file__).resolve().parents[1]
ORDERS = ROOT / "examples/manufacturing_cost_control/orders.json"
ISSUES = ROOT / "examples/manufacturing_cost_control/issues.json"
COMPLETIONS = ROOT / "examples/manufacturing_cost_control/completions.json"
SCRAP = ROOT / "examples/manufacturing_cost_control/scrap.json"


def _report(tmp_path: Path) -> dict[str, object]:
    report_path = tmp_path / "manufacturing-report.json"
    run = run_manufacturing_cost_control_files(
        ORDERS,
        ISSUES,
        COMPLETIONS,
        SCRAP,
        currency="EUR",
        tolerance="0.01",
        max_scrap_quantity="2",
        unit="PCS",
    )
    write_manufacturing_report(run, report_path)
    return verify_manufacturing_report(report_path)


def test_postgres_manufacturing_cost_control_schema_is_rls_immutable_and_bounded() -> None:
    assert "JSONB NOT NULL" in POSTGRES_MANUFACTURING_COST_CONTROL_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_MANUFACTURING_COST_CONTROL_SCHEMA_SQL
    assert "tenant_id = current_setting('app.tenant_id', true)" in POSTGRES_MANUFACTURING_COST_CONTROL_SCHEMA_SQL
    assert "workspace_id = current_setting('app.workspace_id', true)" in POSTGRES_MANUFACTURING_COST_CONTROL_SCHEMA_SQL
    assert "manufacturing cost-control evidence is immutable" in POSTGRES_MANUFACTURING_COST_CONTROL_SCHEMA_SQL
    assert "manufacturing cost-control evidence cannot be deleted" in POSTGRES_MANUFACTURING_COST_CONTROL_SCHEMA_SQL
    assert "secret" not in POSTGRES_MANUFACTURING_COST_CONTROL_SCHEMA_SQL.casefold()


def test_postgres_manufacturing_cost_control_migration_is_versioned_and_non_destructive() -> None:
    migration = (ROOT / "alembic/versions/0083_postgres_manufacturing_cost_control.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "0083_pg_manufacturing"' in migration
    assert 'down_revision = "0082_pg_cert_evidence"' in migration
    assert "POSTGRES_MANUFACTURING_COST_CONTROL_SCHEMA_SQL" in migration
    assert "refusing to discard manufacturing cost-control evidence" in migration
    assert "DROP TABLE IF EXISTS reconforge.manufacturing_cost_control_runs" in migration


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_manufacturing_cost_control_is_scoped_idempotent_and_append_only(
    tmp_path: Path,
) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")

    tenant_id = "mfgpg_" + uuid4().hex[:10]
    other_tenant = "mfgpg_other_" + uuid4().hex[:8]
    workspace_id = "manufacturing-workspace"
    report = _report(tmp_path)
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_connection = None
    connection = None
    try:
        admin_connection = admin_factory.connect()
        with admin_connection.transaction():
            install_postgres_rls_schema(admin_connection)
            admin_connection.execute(POSTGRES_MANUFACTURING_COST_CONTROL_SCHEMA_SQL)
            admin_connection.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin_connection.execute(
                "GRANT SELECT, INSERT ON reconforge.manufacturing_cost_control_runs TO " f"{app_user}"
            )
            admin_connection.execute(
                "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s), (%s, %s)",
                (tenant_id, tenant_id, other_tenant, other_tenant),
            )
        connection = app_factory.connect()
        repository = PostgresManufacturingCostControlRepository(connection)
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
        with pytest.raises(psycopg.Error, match="immutable"), admin_connection.transaction():
            admin_connection.execute(
                "UPDATE reconforge.manufacturing_cost_control_runs SET prepared_by='tampered' "
                "WHERE tenant_id=%s AND workspace_id=%s",
                (tenant_id, workspace_id),
            )
    finally:
        if connection is not None:
            connection.close()
        if admin_connection is not None:
            admin_connection.close()
