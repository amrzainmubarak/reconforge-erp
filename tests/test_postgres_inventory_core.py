from __future__ import annotations

import importlib.util
import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from reconforge.application.inventory_core import InventoryCoreRepositoryProtocol
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
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data_application import (
    install_postgres_master_data_application_schema,
)
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def _migration() -> ModuleType:
    path = ROOT / "alembic/versions/0024_postgres_inventory_core.py"
    spec = importlib.util.spec_from_file_location("migration_0024", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_core_schema_covers_complete_aggregate_with_forced_rls() -> None:
    tables = (
        "inventory_units_of_measure",
        "inventory_items",
        "inventory_warehouses",
        "inventory_locations",
        "inventory_lots",
        "inventory_movements",
        "inventory_movement_lines",
    )
    for table in tables:
        assert f"CREATE TABLE IF NOT EXISTS reconforge.{table}" in POSTGRES_INVENTORY_CORE_SCHEMA_SQL
    assert "ENABLE ROW LEVEL SECURITY" in POSTGRES_INVENTORY_CORE_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_INVENTORY_CORE_SCHEMA_SQL
    assert "current_setting(''app.tenant_id'',true)" in POSTGRES_INVENTORY_CORE_SCHEMA_SQL


def test_inventory_core_schema_uses_exact_scaled_quantities_and_tenant_links() -> None:
    assert "quantity_scaled BIGINT NOT NULL" in POSTGRES_INVENTORY_CORE_SCHEMA_SQL
    assert "quantity_precision INTEGER NOT NULL" in POSTGRES_INVENTORY_CORE_SCHEMA_SQL
    assert "DOUBLE PRECISION" not in POSTGRES_INVENTORY_CORE_SCHEMA_SQL
    assert " REAL " not in POSTGRES_INVENTORY_CORE_SCHEMA_SQL
    for parent in (
        "domain_workspaces",
        "organizations",
        "legal_entities",
        "fiscal_periods",
        "inventory_units_of_measure",
        "inventory_items",
        "inventory_warehouses",
        "inventory_locations",
        "inventory_lots",
        "inventory_movements",
    ):
        assert f"REFERENCES reconforge.{parent}(tenant_id,id)" in POSTGRES_INVENTORY_CORE_SCHEMA_SQL


def test_inventory_database_guards_final_movement_and_metadata() -> None:
    assert "posted inventory movement lines are immutable" in POSTGRES_INVENTORY_CORE_SCHEMA_SQL
    assert "invalid inventory movement status transition" in POSTGRES_INVENTORY_CORE_SCHEMA_SQL
    assert "posted inventory movement headers are immutable" in POSTGRES_INVENTORY_CORE_SCHEMA_SQL
    assert "inventory movement posting requires lines and review metadata" in POSTGRES_INVENTORY_CORE_SCHEMA_SQL
    assert "voiding an inventory movement requires actor timestamp and reason" in POSTGRES_INVENTORY_CORE_SCHEMA_SQL


def test_inventory_core_migration_is_linear_and_child_first() -> None:
    migration = _migration()
    assert migration.revision == "0024_postgres_inventory_core"
    assert migration.down_revision == "0023_postgres_matching_app"
    source = (ROOT / "alembic/versions/0024_postgres_inventory_core.py").read_text(encoding="utf-8")
    positions = [
        source.index(f'"{table}"')
        for table in (
            "inventory_movement_lines",
            "inventory_movements",
            "inventory_lots",
            "inventory_locations",
            "inventory_warehouses",
            "inventory_items",
            "inventory_units_of_measure",
        )
    ]
    assert positions == sorted(positions)


def test_inventory_core_adapter_exposes_complete_master_data_surface() -> None:
    expected = {
        "upsert_uom",
        "list_uoms",
        "upsert_item",
        "list_items",
        "upsert_warehouse",
        "list_warehouses",
        "upsert_location",
        "list_locations",
        "upsert_lot",
        "list_lots",
    }
    assert expected <= set(dir(PostgresInventoryCoreRepository))


def test_inventory_core_adapter_exposes_draft_write_and_read_surface() -> None:
    assert {"create_movement", "get_movement", "post_movement", "void_movement", "list_movements"} <= set(
        dir(PostgresInventoryCoreRepository)
    )


def test_inventory_core_adapter_matches_all_nineteen_protocol_signatures() -> None:
    operations = [
        name
        for name, value in vars(InventoryCoreRepositoryProtocol).items()
        if callable(value) and not name.startswith("_")
    ]
    assert len(operations) == 19
    for name in operations:
        protocol = inspect.signature(getattr(InventoryCoreRepositoryProtocol, name))
        adapter = inspect.signature(getattr(PostgresInventoryCoreRepository, name))
        assert [(p.name, p.kind, p.default) for p in protocol.parameters.values()] == [
            (p.name, p.kind, p.default) for p in adapter.parameters.values()
        ], name


def test_inventory_core_adapter_contains_hierarchy_tracking_and_evidence_guards() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_inventory_core.py").read_text(encoding="utf-8")
    assert "WITH RECURSIVE descendants" in source
    assert "Inventory location hierarchy must remain acyclic." in source
    assert "Lot/serial references require an item configured for Lot or Serial tracking." in source
    assert "PostgresAuditEventRepository" in source
    assert "encode_postgres_outbox_payload" in source
    assert "quantity_to_scaled" in source
    assert "A serial number can appear only once in one inventory movement." in source
    assert "Inventory movements require an Open fiscal period containing the movement date." in source
    assert "FOR UPDATE" in source
    assert "pg_advisory_xact_lock(hashtextextended(%s,0))" in source
    assert "same_actor" in source
    assert "Inventory movement would create negative stock in a protected location." in source
    assert "Serial tracking permits exactly zero or one on-hand unit per serial number." in source
    assert "Approved inventory valuation" in source
    assert "must be reversed before voiding its movement." in source


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_inventory_lifecycle_stock_controls_and_rls() -> None:
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
    tenant_a, tenant_b = "inventory_a_" + uuid4().hex[:8], "inventory_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            install_postgres_master_data_application_schema(admin)
            install_postgres_finance_core_schema(admin)
            admin.execute(POSTGRES_INVENTORY_CORE_SCHEMA_SQL)
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
            repository = PostgresInventoryCoreRepository(connection, tenant_a)
            repository.upsert_uom(
                uom_code="KG", name="Kilogram", category="Weight", decimal_places=3, workspace="Inventory"
            )
            repository.upsert_item(
                item_code="MATERIAL", name="Material", organization_code="ORG", uom_code="KG", workspace="Inventory"
            )
            repository.upsert_warehouse(
                warehouse_code="MAIN", name="Main", organization_code="ORG", entity_code="ENTITY", workspace="Inventory"
            )
            repository.upsert_location(
                warehouse_code="MAIN",
                location_code="STOCK",
                name="Stock",
                organization_code="ORG",
                workspace="Inventory",
            )
            receipt = repository.create_movement(
                movement_number="RCPT-1",
                movement_type="Receipt",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id=f"period-{tenant_a}",
                movement_date="2026-07-28",
                description="Synthetic receipt",
                lines=[{"item_code": "MATERIAL", "quantity": "2.500", "to_location": "MAIN/STOCK"}],
                workspace="Inventory",
                actor_label="maker",
            )
            with pytest.raises(PlatformError, match="Segregation of duties"):
                repository.post_movement(str(receipt["id"]), reason="Self post", actor_label="maker")
            repository.post_movement(str(receipt["id"]), reason="Independent review", actor_label="checker")
            delivery = repository.create_movement(
                movement_number="SHIP-1",
                movement_type="Delivery",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id=f"period-{tenant_a}",
                movement_date="2026-07-28",
                description="Synthetic delivery",
                lines=[{"item_code": "MATERIAL", "quantity": "1.000", "from_location": "MAIN/STOCK"}],
                workspace="Inventory",
                actor_label="maker",
            )
            repository.post_movement(str(delivery["id"]), reason="Independent review", actor_label="checker")
            assert (
                repository.on_hand(organization_code="ORG", entity_code="ENTITY", workspace="Inventory")["balances"][0][
                    "quantity"
                ]
                == "1.500"
            )
            with pytest.raises(PlatformError, match="negative stock"):
                repository.void_movement(str(receipt["id"]), reason="Unsafe reversal", actor_label="checker")
            assert (
                repository.void_movement(str(delivery["id"]), reason="Safe reversal", actor_label="checker")["status"]
                == "Voided"
            )
            assert repository.summary(workspace="Inventory").posted_movements == 1
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            repository = PostgresInventoryCoreRepository(connection, tenant_b)
            assert repository.list_movements(workspace="Inventory") == []
            assert repository.list_items(workspace="Inventory") == []
    finally:
        for tenant in (tenant_a, tenant_b):
            try:
                with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                    connection.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant,))
            except psycopg.Error:
                pass
        admin.close()
