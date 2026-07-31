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
from reconforge.infrastructure.postgres_execution_scope import (
    POSTGRES_EXECUTION_SCOPE_SCHEMA_SQL,
    install_postgres_execution_scope_schema,
)


class _Connection:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def execute(self, sql: str) -> None:
        self.sql.append(sql)


def test_execution_scope_policies_cover_hierarchy_and_are_installable() -> None:
    normalized = " ".join(POSTGRES_EXECUTION_SCOPE_SCHEMA_SQL.split())
    for table_name in (
        "domain_workspaces",
        "domain_periods",
        "master_data_workspace_organizations",
        "organizations",
        "legal_entities",
        "branches",
    ):
        assert f"ON reconforge.{table_name}" in normalized
    for setting in (
        "app.tenant_id",
        "app.workspace_id",
        "app.organization_id",
        "app.legal_entity_id",
    ):
        assert setting in normalized
    connection = _Connection()
    install_postgres_execution_scope_schema(connection)
    assert connection.sql == [POSTGRES_EXECUTION_SCOPE_SCHEMA_SQL]


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_execution_scope_denies_sibling_workspace_organization_and_entity() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    token = uuid4().hex[:8]
    tenant = f"scope_{token}"
    workspace_a, workspace_b = f"ws_a_{token}", f"ws_b_{token}"
    organization_a, organization_b = f"org_a_{token}", f"org_b_{token}"
    entity_a, entity_b = f"ent_a_{token}", f"ent_b_{token}"
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT ON reconforge.domain_workspaces, reconforge.domain_periods, "
                f"reconforge.organizations, reconforge.legal_entities, reconforge.branches, "
                f"reconforge.master_data_workspace_organizations TO {app_user}"
            )
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant, tenant))
            for workspace in (workspace_a, workspace_b):
                admin.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
                    (tenant, workspace, workspace),
                )
            for organization, workspace in ((organization_a, workspace_a), (organization_b, workspace_b)):
                admin.execute(
                    "INSERT INTO reconforge.organizations(tenant_id,id,name,application_workspace_id) "
                    "VALUES(%s,%s,%s,%s)",
                    (tenant, organization, organization, workspace),
                )
                admin.execute(
                    "INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) "
                    "VALUES(%s,%s,%s)",
                    (tenant, workspace, organization),
                )
            admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,'USD','US Dollar',2)", (tenant,))
            for entity, organization, code in ((entity_a, organization_a, "EA"), (entity_b, organization_b, "EB")):
                admin.execute(
                    "INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) "
                    "VALUES(%s,%s,%s,%s,%s,'USD')",
                    (tenant, entity, organization, code, entity),
                )
        with PostgresTenantBoundary(app_factory).transaction(tenant) as connection:
            assert connection.execute("SELECT count(*) FROM reconforge.domain_workspaces").fetchone()[0] == 2
        with PostgresTenantBoundary(app_factory).transaction(
            tenant,
            organization_id=organization_a,
            workspace_id=workspace_a,
            legal_entity_id=entity_a,
        ) as connection:
            assert connection.execute("SELECT id FROM reconforge.domain_workspaces").fetchone()[0] == workspace_a
            assert connection.execute("SELECT id FROM reconforge.organizations").fetchone()[0] == organization_a
            assert connection.execute("SELECT id FROM reconforge.legal_entities").fetchone()[0] == entity_a
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute(
                    "INSERT INTO reconforge.domain_periods(tenant_id,id,workspace_id,name,start_date,end_date,status,created_at) "
                    "VALUES(%s,%s,%s,'blocked','2026-01-01','2026-01-31','Open','2026-01-01')",
                    (tenant, f"period_{token}", workspace_b),
                )
    finally:
        with admin.transaction():
            admin.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant,))
        admin.close()
