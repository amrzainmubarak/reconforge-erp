from __future__ import annotations

import importlib.util
import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import uuid4

import pytest

from reconforge.application.inventory_planning import InventoryPlanningRepositoryProtocol
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_finance_core import install_postgres_finance_core_schema
from reconforge.infrastructure.postgres_inventory_core import (
    POSTGRES_INVENTORY_CORE_SCHEMA_SQL,
    PostgresInventoryCoreRepository,
)
from reconforge.infrastructure.postgres_inventory_planning import (
    POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL,
    PostgresInventoryPlanningRepository,
)
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data_application import (
    install_postgres_master_data_application_schema,
)
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def _migration() -> ModuleType:
    path = ROOT / "alembic/versions/0027_postgres_inventory_planning.py"
    spec = importlib.util.spec_from_file_location("migration_0027", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_planning_schema_has_exact_tenant_aggregate_and_forced_rls() -> None:
    for table in ("inventory_count_sessions", "inventory_count_lines", "inventory_reorder_rules"):
        assert f"CREATE TABLE IF NOT EXISTS reconforge.{table}" in POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL
        assert f"'{table}'" in POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL
    assert "expected_quantity_scaled BIGINT" in POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL
    assert "minimum_quantity_scaled BIGINT" in POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL
    assert "DOUBLE PRECISION" not in POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL


def test_planning_schema_has_tenant_links_lifecycle_and_adjustment_guards() -> None:
    for parent in (
        "domain_workspaces",
        "organizations",
        "legal_entities",
        "fiscal_periods",
        "inventory_locations",
        "inventory_movements",
        "inventory_count_sessions",
        "inventory_items",
        "inventory_units_of_measure",
    ):
        assert f"REFERENCES reconforge.{parent}(tenant_id,id)" in POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL
    assert "invalid inventory count status transition" in POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL
    assert "maker checker and exact Draft adjustment evidence" in POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL
    assert "inventory count snapshot fields are immutable" in POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL
    assert "approved inventory count adjustment movement evidence is immutable" in POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL


def test_planning_migration_is_linear_and_child_first() -> None:
    migration = _migration()
    assert migration.revision == "0027_postgres_inventory_planning"
    assert migration.down_revision == "0026_postgres_inventory_reverse"
    source = (ROOT / "alembic/versions/0027_postgres_inventory_planning.py").read_text(encoding="utf-8")
    assert source.index("inventory_count_lines CASCADE") < source.index("inventory_count_sessions CASCADE")
    assert "inventory_count_adjustment_lines_guard" in source


def test_planning_adapter_matches_all_thirteen_application_signatures() -> None:
    methods = [
        name
        for name, value in vars(InventoryPlanningRepositoryProtocol).items()
        if callable(value) and not name.startswith("_")
    ]
    assert len(methods) == 13
    for name in methods:
        assert inspect.signature(getattr(PostgresInventoryPlanningRepository, name)) == inspect.signature(
            getattr(InventoryPlanningRepositoryProtocol, name)
        )


def test_planning_adapter_serializes_counts_and_emits_transactional_evidence() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_inventory_planning.py").read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in source
    assert "Posted inventory changed after this count started" in source
    assert "Segregation of duties prevents approving a count you created or submitted." in source
    assert "'Adjustment',%s,%s,%s,'Generated','Draft'" in source
    assert "PostgresAuditEventRepository" in source
    assert "encode_postgres_outbox_payload" in source
    assert '"external_calls": False' in source


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_count_adjustment_reorder_and_rls() -> None:
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
    tenant_a, tenant_b = "planning_a_" + uuid4().hex[:8], "planning_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            install_postgres_master_data_application_schema(admin)
            install_postgres_finance_core_schema(admin)
            admin.execute(POSTGRES_INVENTORY_CORE_SCHEMA_SQL)
            admin.execute(POSTGRES_INVENTORY_PLANNING_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        for tenant in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                workspace_id, organization_id, entity_id = f"workspace-{tenant}", f"org-{tenant}", f"entity-{tenant}"
                connection.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'Inventory')",
                    (tenant, workspace_id),
                )
                connection.execute(
                    "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,'USD','US Dollar',2)",
                    (tenant,),
                )
                connection.execute(
                    "INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,active) VALUES (%s,%s,'ORG','Organization','USD',TRUE)",
                    (tenant, organization_id),
                )
                connection.execute(
                    "INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) VALUES (%s,%s,%s)",
                    (tenant, workspace_id, organization_id),
                )
                connection.execute(
                    "INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES (%s,%s,%s,'ENTITY','Entity','USD')",
                    (tenant, entity_id, organization_id),
                )
                connection.execute(
                    "INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number) VALUES (%s,%s,%s,'2026-07-01','2026-07-31',2026,7)",
                    (tenant, f"period-{tenant}", f"2026-07-{tenant}"),
                )
                connection.execute(
                    "INSERT INTO reconforge.master_data_workspace_periods(tenant_id,workspace_id,period_id) VALUES (%s,%s,%s)",
                    (tenant, workspace_id, f"period-{tenant}"),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            inventory = PostgresInventoryCoreRepository(connection, tenant_a)
            inventory.upsert_uom(
                uom_code="KG", name="Kilogram", category="Weight", decimal_places=3, workspace="Inventory"
            )
            inventory.upsert_item(
                item_code="MATERIAL", name="Material", organization_code="ORG", uom_code="KG", workspace="Inventory"
            )
            inventory.upsert_warehouse(
                warehouse_code="MAIN", name="Main", organization_code="ORG", entity_code="ENTITY", workspace="Inventory"
            )
            inventory.upsert_location(
                warehouse_code="MAIN", location_code="STOCK", name="Stock", organization_code="ORG", workspace="Inventory"
            )
            receipt = inventory.create_movement(
                movement_number="RCPT-COUNT-1",
                movement_type="Receipt",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id=f"period-{tenant_a}",
                movement_date="2026-07-27",
                description="Synthetic count receipt",
                lines=[{"item_code": "MATERIAL", "quantity": "2.500", "to_location": "MAIN/STOCK"}],
                workspace="Inventory",
                actor_label="maker",
            )
            inventory.post_movement(str(receipt["id"]), reason="Independent review", actor_label="checker")
            planning = PostgresInventoryPlanningRepository(connection, tenant_a)
            count = planning.create_count_session(
                count_number="COUNT-1",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id=f"period-{tenant_a}",
                count_date="2026-07-28",
                warehouse_code="MAIN",
                location_code="STOCK",
                description="Synthetic governed count",
                workspace="Inventory",
                actor_label="maker",
            )
            started = planning.start_count_session(str(count["id"]), actor_label="maker")
            assert started["lines"][0]["expected_quantity"] == "2.500"
            planning.record_counted_quantity(
                str(count["id"]),
                str(started["lines"][0]["id"]),
                counted_quantity="2.000",
                actor_label="maker",
            )
            planning.submit_count_session(str(count["id"]), reason="Count complete", actor_label="maker")
            with pytest.raises(PlatformError, match="Segregation of duties"):
                planning.approve_count_session(str(count["id"]), reason="Self approval", actor_label="maker")
            approved = planning.approve_count_session(
                str(count["id"]), reason="Independent approval", actor_label="checker"
            )
            assert approved["status"] == "Approved"
            assert approved["lines"][0]["variance_quantity"] == "-0.500"
            movement = connection.execute(
                "SELECT movement_type,status,source_reference FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s",
                (tenant_a, approved["adjustment_movement_id"]),
            ).fetchone()
            assert tuple(movement) == ("Adjustment", "Draft", count["id"])
            planning.upsert_reorder_rule(
                organization_code="ORG",
                entity_code="ENTITY",
                item_code="MATERIAL",
                warehouse_code="MAIN",
                location_code="STOCK",
                minimum_quantity="3.000",
                target_quantity="5.000",
                lead_time_days=2,
                workspace="Inventory",
                actor_label="planner",
            )
            signals = cast(
                dict[str, Any],
                planning.reorder_signals(organization_code="ORG", entity_code="ENTITY", workspace="Inventory"),
            )
            assert signals["summary"] == {"total": 1, "high": 0, "medium": 1}
            assert signals["signals"][0]["suggested_quantity"] == "2.500"
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            planning_b = PostgresInventoryPlanningRepository(connection, tenant_b)
            assert planning_b.list_count_sessions(workspace="Inventory") == []
            assert planning_b.list_reorder_rules(workspace="Inventory") == []
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        except psycopg.Error:
            pass
        admin.close()
