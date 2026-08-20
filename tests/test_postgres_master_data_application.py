from __future__ import annotations

import importlib.util
import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from reconforge.application.master_data import MasterDataRepository
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import (
    POSTGRES_FISCAL_PERIOD_SCHEMA_SQL,
    POSTGRES_MASTER_DATA_SCHEMA_SQL,
)
from reconforge.infrastructure.postgres_master_data_application import (
    POSTGRES_CURRENCY_REGISTRY_BINDING_SCHEMA_SQL,
    POSTGRES_CURRENCY_REGISTRY_SNAPSHOT_SCHEMA_SQL,
    POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL,
    PostgresMasterDataApplicationRepository,
    install_postgres_master_data_application_schema,
)

ROOT = Path(__file__).resolve().parents[1]


def _migration() -> ModuleType:
    path = ROOT / "alembic/versions/0020_postgres_master_data_application.py"
    spec = importlib.util.spec_from_file_location("migration_0020", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_master_data_application_adapter_implements_complete_port() -> None:
    methods = (
        "upsert_currency",
        "list_currencies",
        "upsert_organization",
        "list_organizations",
        "upsert_legal_entity",
        "list_legal_entities",
        "upsert_branch",
        "list_branches",
        "upsert_period",
        "set_period_status",
        "list_periods",
        "summary",
        "snapshot",
        "currency_registry_reconciliation",
        "currency_registry_binding",
        "currency_registry_context",
        "bind_currency_registry",
    )
    for method_name in methods:
        adapter = inspect.signature(getattr(PostgresMasterDataApplicationRepository, method_name))
        protocol = inspect.signature(getattr(MasterDataRepository, method_name))
        assert tuple(adapter.parameters) == tuple(protocol.parameters)
        for name, parameter in adapter.parameters.items():
            assert parameter.kind == protocol.parameters[name].kind
            assert parameter.default == protocol.parameters[name].default


def test_master_data_application_schema_preserves_workspace_scope_and_forced_rls() -> None:
    assert "application_workspace_id TEXT" in POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL
    assert "idx_organizations_workspace_code" in POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL
    assert "idx_fiscal_periods_workspace_name" in POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL
    assert "master_data_workspace_organizations" in POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL
    assert "master_data_workspace_periods" in POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL
    assert POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 2
    assert POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL.count("CREATE POLICY tenant_scope") == 2
    assert "currency_registry_bindings" in POSTGRES_CURRENCY_REGISTRY_BINDING_SCHEMA_SQL
    assert POSTGRES_CURRENCY_REGISTRY_BINDING_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 1
    assert POSTGRES_CURRENCY_REGISTRY_BINDING_SCHEMA_SQL.count("CREATE POLICY tenant_scope") == 1
    assert "currency_registry_snapshots" in POSTGRES_CURRENCY_REGISTRY_SNAPSHOT_SCHEMA_SQL
    assert POSTGRES_CURRENCY_REGISTRY_SNAPSHOT_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 1
    assert POSTGRES_CURRENCY_REGISTRY_SNAPSHOT_SCHEMA_SQL.count("CREATE POLICY tenant_scope") == 1


def test_master_data_application_migration_is_linear_and_rolls_back_scope_assets() -> None:
    migration = _migration()
    assert migration.revision == "0020_postgres_master_data_app"
    assert migration.down_revision == "0019_postgres_finance_core"
    source = (ROOT / "alembic/versions/0020_postgres_master_data_application.py").read_text(encoding="utf-8")
    assert source.index("DROP TABLE IF EXISTS reconforge.master_data_workspace_periods") < source.index(
        "DROP TABLE IF EXISTS reconforge.master_data_workspace_organizations"
    )
    assert "DROP COLUMN IF EXISTS application_workspace_id" in source


def test_workspace_scope_is_used_for_identity_overlap_and_reads() -> None:
    adapter = (ROOT / "reconforge/infrastructure/postgres_master_data_application.py").read_text(encoding="utf-8")
    assert "application_workspace_id=%s" in adapter
    assert "idx_organizations_workspace_code" in adapter
    assert "links.workspace_id=%s" in adapter
    assert "set_local_tenant_scope" in adapter
    assert "Organization reference was not found in the selected workspace" in adapter


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_master_data_application_workspace_and_tenant_isolation() -> None:
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
    tenant_a = "master_app_a_" + uuid4().hex[:8]
    tenant_b = "master_app_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_FISCAL_PERIOD_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            install_postgres_domain_schema(admin)
            install_postgres_master_data_application_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            tables = (
                "tenants,organizations,currencies,legal_entities,branches,fiscal_periods,domain_workspaces,"
                "domain_audit_ledger_state,domain_audit_events,outbox_events,audit_events,"
                "master_data_workspace_organizations,master_data_workspace_periods,currency_registry_snapshots,currency_registry_bindings"
            )
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{tables.replace(',', ',reconforge.')} TO {app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        for tenant in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                connection.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,%s),(%s,%s,%s)",
                    (tenant, f"finance-{tenant}", "Finance", tenant, f"ops-{tenant}", "Operations"),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresMasterDataApplicationRepository(connection, tenant_a)
            repository.upsert_currency(code="KWD", name="Kuwaiti Dinar", minor_units=3, actor_label="admin")
            finance_org = repository.upsert_organization(
                organization_code="FIN", name="Finance", workspace="Finance", actor_label="admin"
            )
            repository.upsert_organization(
                organization_code="OPS", name="Operations", workspace="Operations", actor_label="admin"
            )
            repository.upsert_legal_entity(
                organization_code="FIN",
                entity_code="ENTITY",
                name="Finance Entity",
                currency_code="KWD",
                workspace="Finance",
                actor_label="admin",
            )
            repository.upsert_branch(
                organization_code="FIN",
                branch_code="HQ",
                name="Head Office",
                entity_code="ENTITY",
                workspace="Finance",
                actor_label="admin",
            )
            finance_period = repository.upsert_period(
                name="2026-07",
                start_date="2026-07-01",
                end_date="2026-07-31",
                workspace="Finance",
                actor_label="admin",
            )
            binding = repository.bind_currency_registry(workspace="Finance", actor_label="admin")
            assert binding["registry_digest"]
            assert repository.currency_registry_reconciliation(workspace="Finance")["binding"]["status"] == "current"
            operations_period = repository.upsert_period(
                name="2026-07",
                start_date="2026-07-01",
                end_date="2026-07-31",
                workspace="Operations",
                actor_label="admin",
            )
            assert finance_org["organization_code"] == "FIN"
            assert finance_period["id"] != operations_period["id"]
            assert [row["organization_code"] for row in repository.list_organizations(workspace="Finance")] == ["FIN"]
            assert [row["organization_code"] for row in repository.list_organizations(workspace="Operations")] == [
                "OPS"
            ]
            assert repository.summary(workspace="Finance").to_dict() == {
                "workspace": "Finance",
                "organizations": 1,
                "legal_entities": 1,
                "branches": 1,
                "periods": 1,
                "active_currencies": 1,
            }
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM reconforge.domain_audit_events WHERE tenant_id=%s", (tenant_a,)
                ).fetchone()[0]
                >= 2
            )
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            repository = PostgresMasterDataApplicationRepository(connection, tenant_b)
            assert repository.list_organizations(workspace="Finance") == []
            assert repository.list_periods(workspace="Finance") == []
    finally:
        for tenant in (tenant_a, tenant_b):
            try:
                with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                    connection.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant,))
            except psycopg.Error:
                pass
        admin.close()
