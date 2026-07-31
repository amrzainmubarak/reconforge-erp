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
from reconforge.infrastructure.postgres_accounts import POSTGRES_ACCOUNTS_SCHEMA_SQL
from reconforge.infrastructure.postgres_approvals import POSTGRES_APPROVALS_SCHEMA_SQL
from reconforge.infrastructure.postgres_business_scope import POSTGRES_BUSINESS_SCOPE_SCHEMA_SQL
from reconforge.infrastructure.postgres_close_application import POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL
from reconforge.infrastructure.postgres_evidence_application import POSTGRES_EVIDENCE_APPLICATION_SCHEMA_SQL
from reconforge.infrastructure.postgres_exceptions import POSTGRES_EXCEPTIONS_SCHEMA_SQL
from reconforge.infrastructure.postgres_inventory_core import POSTGRES_INVENTORY_CORE_SCHEMA_SQL
from reconforge.infrastructure.postgres_inventory_planning import POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL
from reconforge.infrastructure.postgres_inventory_valuation import POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
from reconforge.infrastructure.postgres_inventory_valuation_reversal import (
    POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL,
)
from reconforge.infrastructure.postgres_matching import POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL
from reconforge.infrastructure.postgres_payables import POSTGRES_PAYABLES_SCHEMA_SQL
from reconforge.infrastructure.postgres_receivables import POSTGRES_RECEIVABLES_SCHEMA_SQL

_BUSINESS_SCHEMA_REINSTALLERS = (
    POSTGRES_ACCOUNTS_SCHEMA_SQL,
    POSTGRES_APPROVALS_SCHEMA_SQL,
    POSTGRES_CLOSE_APPLICATION_SCHEMA_SQL,
    POSTGRES_EVIDENCE_APPLICATION_SCHEMA_SQL,
    POSTGRES_EXCEPTIONS_SCHEMA_SQL,
    POSTGRES_INVENTORY_CORE_SCHEMA_SQL,
    POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL,
    POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL,
    POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL,
    POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL,
    POSTGRES_PAYABLES_SCHEMA_SQL,
    POSTGRES_RECEIVABLES_SCHEMA_SQL,
)


def test_business_scope_migration_composes_every_direct_scope_dimension() -> None:
    sql = POSTGRES_BUSINESS_SCOPE_SCHEMA_SQL
    for column, setting in (
        ("workspace_id", "app.workspace_id"),
        ("application_workspace_id", "app.workspace_id"),
        ("organization_id", "app.organization_id"),
        ("legal_entity_id", "app.legal_entity_id"),
        ("entity_id", "app.entity_id"),
        ("branch_id", "app.branch_id"),
    ):
        assert column in sql
        assert setting in sql
    assert "USING (%2$s) WITH CHECK (%2$s)" in sql
    assert "information_schema.columns" in sql
    assert "parent.tenant_id=%2$I.tenant_id" in sql
    for child, parent in (
        ("account_reconciliation_items", "account_reconciliation_records"),
        ("finance_entry_lines", "finance_entries"),
        ("inventory_count_lines", "inventory_count_sessions"),
        ("inventory_movement_lines", "inventory_movements"),
        ("ledger_lines", "ledger_entries"),
    ):
        assert f"'{child}','{parent}'" in sql


def test_business_scope_does_not_weaken_purpose_built_hierarchy_policies() -> None:
    sql = POSTGRES_BUSINESS_SCOPE_SCHEMA_SQL
    for table in (
        "branches",
        "domain_periods",
        "domain_workspaces",
        "durable_jobs",
        "legal_entities",
        "master_data_workspace_organizations",
        "organizations",
    ):
        assert f"'{table}'" in sql


def test_business_schema_reinstallers_preserve_composed_scope_policies() -> None:
    for schema in _BUSINESS_SCHEMA_REINSTALLERS:
        assert "DROP POLICY IF EXISTS tenant_isolation" in schema
        assert "policyname='tenant_scope'" in schema


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_schema_reinstall_preserves_composed_business_policies() -> None:
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN")
    if not admin_dsn:
        pytest.skip("requires a disposable PostgreSQL administration service")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    connection = factory.connect()
    try:
        with connection.transaction():
            for schema in _BUSINESS_SCHEMA_REINSTALLERS:
                connection.execute(schema)
        duplicates = connection.execute(
            "SELECT tablename FROM pg_policies WHERE schemaname='reconforge' "
            "GROUP BY tablename HAVING bool_or(policyname='tenant_scope') "
            "AND bool_or(policyname='tenant_isolation') ORDER BY tablename"
        ).fetchall()
        assert duplicates == []
    finally:
        connection.close()


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_business_scope_denies_sibling_workspace_read_and_write() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    token = uuid4().hex[:8]
    tenant = f"business_scope_{token}"
    workspace_a, workspace_b = f"ws_a_{token}", f"ws_b_{token}"
    unit_a, unit_b = f"uom_a_{token}", f"uom_b_{token}"
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT ON reconforge.inventory_units_of_measure TO {app_user}"
            )
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant, tenant))
            for workspace in (workspace_a, workspace_b):
                admin.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
                    (tenant, workspace, workspace),
                )
            for unit, workspace, code in ((unit_a, workspace_a, "EA"), (unit_b, workspace_b, "EB")):
                admin.execute(
                    "INSERT INTO reconforge.inventory_units_of_measure"
                    "(tenant_id,id,workspace_id,uom_code,name) VALUES(%s,%s,%s,%s,%s)",
                    (tenant, unit, workspace, code, unit),
                )
        with PostgresTenantBoundary(app_factory).transaction(tenant, workspace_id=workspace_a) as connection:
            rows = connection.execute(
                "SELECT id FROM reconforge.inventory_units_of_measure ORDER BY id"
            ).fetchall()
            assert [row[0] for row in rows] == [unit_a]
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute(
                    "INSERT INTO reconforge.inventory_units_of_measure"
                    "(tenant_id,id,workspace_id,uom_code,name) VALUES(%s,%s,%s,'HX','Hostile')",
                    (tenant, f"hostile_{token}", workspace_b),
                )
    finally:
        with admin.transaction():
            admin.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant,))
        admin.close()
