from __future__ import annotations

import importlib.util
import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from reconforge.application.inventory_valuation import InventoryValuationRepositoryProtocol
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_finance_core import (
    PostgresFinanceCoreRepository,
    install_postgres_finance_core_schema,
)
from reconforge.infrastructure.postgres_inventory_core import (
    POSTGRES_INVENTORY_CORE_SCHEMA_SQL,
    PostgresInventoryCoreRepository,
)
from reconforge.infrastructure.postgres_inventory_valuation import (
    POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL,
    PostgresInventoryValuationRepository,
)
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data_application import (
    install_postgres_master_data_application_schema,
)
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def _migration() -> ModuleType:
    path = ROOT / "alembic/versions/0025_postgres_inventory_valuation.py"
    spec = importlib.util.spec_from_file_location("migration_0025", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_valuation_schema_covers_fifo_aggregate_with_forced_rls() -> None:
    tables = (
        "inventory_valuation_policies",
        "inventory_valuation_documents",
        "inventory_valuation_input_costs",
        "inventory_valuation_lines",
        "inventory_cost_layers",
        "inventory_layer_consumptions",
    )
    for table in tables:
        assert f"CREATE TABLE IF NOT EXISTS reconforge.{table}" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "costing_method='FIFO'" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "ENABLE ROW LEVEL SECURITY" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL


def test_valuation_schema_uses_exact_minor_values_scaled_quantities_and_tenant_links() -> None:
    assert "total_value_minor BIGINT" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "quantity_scaled BIGINT" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "DOUBLE PRECISION" not in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert " REAL " not in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    for parent in (
        "inventory_movements",
        "inventory_movement_lines",
        "inventory_valuation_policies",
        "inventory_valuation_documents",
        "inventory_valuation_lines",
        "inventory_cost_layers",
        "finance_journals",
        "finance_accounts",
        "finance_entries",
    ):
        assert f"REFERENCES reconforge.{parent}(tenant_id,id)" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL


def test_valuation_database_guards_lifecycle_details_and_layer_depletion() -> None:
    assert "inventory valuations must be created as empty Draft documents" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "invalid inventory valuation status transition" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert (
        "final inventory valuation headers and lifecycle metadata are immutable"
        in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    )
    assert "approved inventory valuation details are immutable" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "inventory valuation lines are immutable" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "inventory cost layer balances must equal immutable consumptions" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "inventory cost layers cannot be deleted" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "inventory layer consumptions are immutable" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "complete layers consumptions and balanced finance draft" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "inventory cost layers require an inbound Draft valuation line" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL
    assert "outbound Draft valuation line" in POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL


def test_valuation_migration_is_linear_and_child_first() -> None:
    migration = _migration()
    assert migration.revision == "0025_postgres_inventory_value"
    assert migration.down_revision == "0024_postgres_inventory_core"
    source = (ROOT / "alembic/versions/0025_postgres_inventory_valuation.py").read_text(encoding="utf-8")
    positions = [
        source.index(f'"{table}"')
        for table in (
            "inventory_layer_consumptions",
            "inventory_cost_layers",
            "inventory_valuation_lines",
            "inventory_valuation_input_costs",
            "inventory_valuation_documents",
            "inventory_valuation_policies",
        )
    ]
    assert positions == sorted(positions)


def test_valuation_adapter_matches_all_eleven_application_signatures() -> None:
    methods = [
        name
        for name, value in vars(InventoryValuationRepositoryProtocol).items()
        if callable(value) and not name.startswith("_")
    ]
    assert len(methods) == 11
    for name in methods:
        assert inspect.signature(getattr(PostgresInventoryValuationRepository, name)) == inspect.signature(
            getattr(InventoryValuationRepositoryProtocol, name)
        )


def test_valuation_adapter_validates_financial_scope_and_exact_inbound_costs() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_inventory_valuation.py").read_text(encoding="utf-8")
    assert "required Finance Core dimensions" in source
    assert "Valuation journal and legal-entity currencies must match." in source
    assert "Only Posted inventory movements can be prepared for valuation." in source
    assert "Transfers do not create valuation documents" in source
    assert "Every inbound movement line requires exactly one input total cost." in source
    assert "amount_to_minor" in source
    assert "PostgresAuditEventRepository" in source
    assert "encode_postgres_outbox_payload" in source


def test_fifo_allocation_uses_half_even_and_preserves_full_layer_residual() -> None:
    allocate = PostgresInventoryValuationRepository._allocated_value
    assert allocate(5, 2, 1) == 2
    assert allocate(7, 2, 1) == 4
    assert allocate(7, 2, 2) == 7


def test_fifo_approval_serializes_layers_and_creates_balanced_finance_draft() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_inventory_valuation.py").read_text(encoding="utf-8")
    assert "ROUND_HALF_EVEN" in source
    assert "pg_advisory_xact_lock" in source
    assert "ORDER BY created_at,id FOR UPDATE" in source
    assert "finance_entries" in source
    assert "finance_entry_lines" in source
    assert "Generated Inventory-to-Finance postings must balance" in source
    assert "Segregation of duties prevents approving your own inventory valuation." in source


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_fifo_valuation_finance_draft_void_guard_and_rls() -> None:
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
    tenant_a, tenant_b = "valuation_a_" + uuid4().hex[:8], "valuation_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            install_postgres_master_data_application_schema(admin)
            install_postgres_finance_core_schema(admin)
            admin.execute(POSTGRES_INVENTORY_CORE_SCHEMA_SQL)
            admin.execute(POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL)
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
            finance = PostgresFinanceCoreRepository(connection, tenant_a)
            finance.upsert_chart(chart_code="DEFAULT", name="Default", workspace="Inventory", organization_code="ORG")
            for code, name, account_type in (
                ("INVENTORY", "Inventory", "Asset"),
                ("CLEARING", "Receipt clearing", "Liability"),
                ("COGS", "Cost of goods sold", "Expense"),
                ("ADJUSTMENT", "Inventory adjustment", "Expense"),
            ):
                finance.upsert_account(
                    account_code=code,
                    name=name,
                    workspace="Inventory",
                    chart_code="DEFAULT",
                    account_type=account_type,
                )
            finance.upsert_journal(
                journal_code="INVENTORY",
                name="Inventory valuation",
                organization_code="ORG",
                currency_code="USD",
                workspace="Inventory",
            )
            inventory = PostgresInventoryCoreRepository(connection, tenant_a)
            inventory.upsert_uom(
                uom_code="KG", name="Kilogram", category="Weight", decimal_places=3, workspace="Inventory"
            )
            inventory.upsert_item(
                item_code="MATERIAL",
                name="Material",
                organization_code="ORG",
                uom_code="KG",
                inventory_account_code="INVENTORY",
                workspace="Inventory",
            )
            inventory.upsert_warehouse(
                warehouse_code="MAIN", name="Main", organization_code="ORG", entity_code="ENTITY", workspace="Inventory"
            )
            inventory.upsert_location(
                warehouse_code="MAIN",
                location_code="STOCK",
                name="Stock",
                organization_code="ORG",
                workspace="Inventory",
            )
            receipt = inventory.create_movement(
                movement_number="RCPT-1",
                movement_type="Receipt",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id=f"period-{tenant_a}",
                movement_date="2026-07-27",
                description="Synthetic valued receipt",
                lines=[{"item_code": "MATERIAL", "quantity": "2.500", "to_location": "MAIN/STOCK"}],
                workspace="Inventory",
                actor_label="maker",
            )
            inventory.post_movement(str(receipt["id"]), reason="Independent review", actor_label="checker")
            valuation = PostgresInventoryValuationRepository(connection, tenant_a)
            valuation.upsert_policy(
                policy_code="FIFO",
                organization_code="ORG",
                entity_code="ENTITY",
                journal_code="INVENTORY",
                receipt_clearing_account_code="CLEARING",
                cogs_account_code="COGS",
                adjustment_account_code="ADJUSTMENT",
                workspace="Inventory",
            )
            receipt_document = valuation.create_document(
                valuation_number="VAL-RCPT-1",
                movement_id=str(receipt["id"]),
                policy_code="FIFO",
                input_costs=[{"line_number": 1, "total_cost": "12.34"}],
                actor_label="maker",
            )
            with pytest.raises(PlatformError, match="Segregation of duties"):
                valuation.approve_document(str(receipt_document["id"]), reason="Self approval", actor_label="maker")
            approved_receipt = valuation.approve_document(
                str(receipt_document["id"]), reason="Independent review", actor_label="checker"
            )
            assert approved_receipt["status"] == "Approved"
            assert approved_receipt["total_value"] == "12.34"
            assert approved_receipt["finance_entry_status"] == "Draft"
            with pytest.raises(PlatformError, match="Approved inventory valuation"):
                inventory.void_movement(str(receipt["id"]), reason="Invalid void", actor_label="checker")
            delivery = inventory.create_movement(
                movement_number="SHIP-1",
                movement_type="Delivery",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id=f"period-{tenant_a}",
                movement_date="2026-07-28",
                description="Synthetic valued issue",
                lines=[{"item_code": "MATERIAL", "quantity": "1.000", "from_location": "MAIN/STOCK"}],
                workspace="Inventory",
                actor_label="maker",
            )
            inventory.post_movement(str(delivery["id"]), reason="Independent review", actor_label="checker")
            issue_document = valuation.create_document(
                valuation_number="VAL-SHIP-1",
                movement_id=str(delivery["id"]),
                policy_code="FIFO",
                actor_label="maker",
            )
            approved_issue = valuation.approve_document(
                str(issue_document["id"]), reason="Independent review", actor_label="checker"
            )
            assert approved_issue["total_value"] == "4.94"
            assert approved_issue["finance_entry_status"] == "Draft"
            layers = valuation.list_cost_layers(workspace="Inventory", open_only=True)
            assert len(layers) == 1
            assert layers[0]["remaining_quantity"] == "1.500"
            assert layers[0]["remaining_value"] == "7.40"
            summary = valuation.summary(workspace="Inventory")
            assert summary.approved_documents == 2
            assert summary.open_layers == 1
            assert summary.unvalued_posted_movements == 0
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            valuation = PostgresInventoryValuationRepository(connection, tenant_b)
            assert valuation.list_policies(workspace="Inventory") == []
            assert valuation.list_documents(workspace="Inventory") == []
            assert valuation.list_cost_layers(workspace="Inventory") == []
    finally:
        for tenant in (tenant_a, tenant_b):
            try:
                with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                    connection.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant,))
            except psycopg.Error:
                pass
        admin.close()
