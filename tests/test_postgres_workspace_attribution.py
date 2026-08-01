from __future__ import annotations

import os
import re
from uuid import uuid4

import pytest

from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_workspace_attribution import (
    POSTGRES_WORKSPACE_ATTRIBUTION_SCHEMA_SQL,
)


def test_workspace_attribution_is_compatible_and_transaction_scoped() -> None:
    sql = POSTGRES_WORKSPACE_ATTRIBUTION_SCHEMA_SQL
    assert "ADD COLUMN IF NOT EXISTS workspace_id TEXT" in sql
    assert "ALTER COLUMN application_workspace_id" in sql
    assert "DEFAULT NULLIF(current_setting(''app.workspace_id'',true),'''')" in sql
    assert "FOREIGN KEY (tenant_id,workspace_id)" in sql
    assert "ON DELETE RESTRICT" in sql
    assert "USING (%2$s) WITH CHECK (%2$s)" in sql


def test_workspace_attribution_covers_business_roots_and_children() -> None:
    sql = POSTGRES_WORKSPACE_ATTRIBUTION_SCHEMA_SQL
    for table in (
        "ap_idempotency_keys",
        "approval_requests",
        "ar_idempotency_keys",
        "certification_records",
        "evidence_registry",
        "evidence_requirements",
        "reconciliation_runs",
        "remediation_plans",
    ):
        assert f"'{table}'" in sql
    for child, parent in (
        ("evidence_links", "evidence_registry"),
        ("reconciliation_inputs", "reconciliation_runs"),
        ("reconciliation_results", "reconciliation_runs"),
        ("reconciliation_exceptions", "reconciliation_runs"),
        ("reconciliation_execution_checkpoints", "reconciliation_runs"),
    ):
        assert f"'{child}','{parent}'" in sql


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_reconciliation_workspace_attribution_hides_sibling_and_legacy_rows() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    token = uuid4().hex[:8]
    tenant = f"attribution_{token}"
    workspace_a, workspace_b = f"ws_a_{token}", f"ws_b_{token}"
    run_a, run_b, legacy_run = f"run_a_{token}", f"run_b_{token}", f"legacy_{token}"
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT ON reconforge.reconciliation_runs, "
                f"reconforge.reconciliation_inputs TO {app_user}"
            )
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant, tenant))
            for workspace in (workspace_a, workspace_b):
                admin.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
                    (tenant, workspace, workspace),
                )
            for run_id, workspace in ((run_a, workspace_a), (run_b, workspace_b), (legacy_run, None)):
                admin.execute(
                    "INSERT INTO reconforge.reconciliation_runs"
                    "(tenant_id,id,workspace_id,name,left_source,right_source,algorithm_version,rule_json,"
                    "input_hash,created_by) VALUES(%s,%s,%s,%s,'left','right','v1','{}',%s,'test')",
                    (tenant, run_id, workspace, run_id, "0" * 64),
                )
                admin.execute(
                    "INSERT INTO reconforge.reconciliation_inputs"
                    "(tenant_id,run_id,side,source_id,record_hash) VALUES(%s,%s,'Left',%s,%s)",
                    (tenant, run_id, f"source_{run_id}", "1" * 64),
                )
        with PostgresTenantBoundary(app_factory).transaction(tenant) as connection:
            assert {row[0] for row in connection.execute(
                "SELECT id FROM reconforge.reconciliation_runs"
            ).fetchall()} == {run_a, run_b, legacy_run}
        with PostgresTenantBoundary(app_factory).transaction(tenant, workspace_id=workspace_a) as connection:
            assert [row[0] for row in connection.execute(
                "SELECT id FROM reconforge.reconciliation_runs ORDER BY id"
            ).fetchall()] == [run_a]
            assert [row[0] for row in connection.execute(
                "SELECT run_id FROM reconforge.reconciliation_inputs ORDER BY run_id"
            ).fetchall()] == [run_a]
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute(
                    "INSERT INTO reconforge.reconciliation_runs"
                    "(tenant_id,id,workspace_id,name,left_source,right_source,algorithm_version,rule_json,"
                    "input_hash,created_by) VALUES(%s,%s,%s,'hostile','left','right','v1','{}',%s,'test')",
                    (tenant, f"hostile_{token}", workspace_b, "2" * 64),
                )
    finally:
        # Reconciliation evidence is intentionally append-only. The live gate
        # uses a disposable database and unique IDs instead of bypassing its
        # deletion guard merely to clean fixtures.
        admin.close()
