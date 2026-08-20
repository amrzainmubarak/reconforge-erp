from __future__ import annotations

import importlib.util
import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from reconforge.application.inventory_valuation_reversal import InventoryValuationReversalRepositoryProtocol
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
from reconforge.infrastructure.postgres_inventory_valuation_reversal import (
    POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL,
    PostgresInventoryValuationReversalRepository,
)
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data_application import (
    install_postgres_master_data_application_schema,
)
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def _migration() -> ModuleType:
    path = ROOT / "alembic/versions/0026_postgres_inventory_valuation_reversal.py"
    spec = importlib.util.spec_from_file_location("migration_0026", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reversal_schema_has_exact_tenant_aggregate_and_forced_rls() -> None:
    for table in ("inventory_valuation_reversals", "inventory_valuation_reversal_effects"):
        assert f"CREATE TABLE IF NOT EXISTS reconforge.{table}" in POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL
        assert f"'{table}'" in POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL
    assert "total_value_minor BIGINT" in POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL
    assert "quantity_scaled BIGINT" in POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL
    assert "DOUBLE PRECISION" not in POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL


def test_reversal_schema_uses_tenant_qualified_lineage_links() -> None:
    for parent in (
        "inventory_valuation_documents",
        "inventory_movements",
        "finance_entries",
        "inventory_valuation_reversals",
        "inventory_valuation_lines",
        "inventory_layer_consumptions",
        "inventory_cost_layers",
    ):
        assert f"REFERENCES reconforge.{parent}(tenant_id,id)" in POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL


def test_reversal_database_guards_exact_effects_dependencies_and_history() -> None:
    schema = POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL
    assert "must be created as empty Draft records" in schema
    assert "exact mirror movement layer effects and finance draft" in schema
    assert "valuation reversal layer effects are immutable" in schema
    assert "cost layer balances must equal immutable consumption and reversal records" in schema
    assert "approved valuation reversal finance evidence is immutable" in schema
    assert "approved valuation reversal movement cannot be voided" in schema
    assert "original_consumption_id=c.id" in schema
    assert "x.quantity_scaled=c.quantity_scaled" in schema
    assert "x.value_minor=c.value_minor" in schema
    assert schema.count("SECURITY DEFINER") == 3
    assert schema.count("SET search_path = pg_catalog, reconforge") == 3


def test_reversal_migration_is_linear_and_restores_layer_guard_on_downgrade() -> None:
    migration = _migration()
    assert migration.revision == "0026_postgres_inventory_reverse"
    assert migration.down_revision == "0025_postgres_inventory_value"
    source = (ROOT / "alembic/versions/0026_postgres_inventory_valuation_reversal.py").read_text(encoding="utf-8")
    assert source.index("inventory_valuation_reversal_effects CASCADE") < source.index(
        "inventory_valuation_reversals CASCADE"
    )
    assert "POSTGRES_INVENTORY_VALUATION_SCHEMA_SQL" in source


def test_reversal_adapter_matches_all_seven_application_signatures() -> None:
    methods = [
        name
        for name, value in vars(InventoryValuationReversalRepositoryProtocol).items()
        if callable(value) and not name.startswith("_")
    ]
    assert len(methods) == 7
    for name in methods:
        assert inspect.signature(getattr(PostgresInventoryValuationReversalRepository, name)) == inspect.signature(
            getattr(InventoryValuationReversalRepositoryProtocol, name)
        )


def test_reversal_adapter_serializes_layers_and_mirrors_finance_with_transactional_evidence() -> None:
    source = (
        ROOT / "reconforge/infrastructure/postgres_inventory_valuation_reversal.py"
    ).read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in source
    assert "ORDER BY id FOR UPDATE" in source
    assert "Segregation of duties prevents approving your own valuation reversal." in source
    assert 'line["credit_minor"]' in source
    assert 'line["debit_minor"]' in source
    assert "PostgresAuditEventRepository" in source
    assert "encode_postgres_outbox_payload" in source
    assert "writes to no external ERP" in source


def test_reversal_type_mapping_rejects_non_compensating_movements() -> None:
    assert PostgresInventoryValuationReversalRepository._expected_type("Receipt") == "Delivery"
    assert PostgresInventoryValuationReversalRepository._expected_type("Delivery") == "Receipt"


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_receipt_reversal_exact_effect_finance_draft_and_rls() -> None:
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
    tenant_a, tenant_b = "reversal_a_" + uuid4().hex[:8], "reversal_b_" + uuid4().hex[:8]
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
            admin.execute(POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL)
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
            for account_code, name, account_type in (
                ("INVENTORY", "Inventory", "Asset"),
                ("CLEARING", "Receipt clearing", "Liability"),
                ("COGS", "Cost of goods sold", "Expense"),
                ("ADJUSTMENT", "Inventory adjustment", "Expense"),
            ):
                finance.upsert_account(
                    account_code=account_code,
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
                movement_number="RCPT-REV-1",
                movement_type="Receipt",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id=f"period-{tenant_a}",
                movement_date="2026-07-27",
                description="Synthetic reversible receipt",
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
            document = valuation.create_document(
                valuation_number="VAL-REV-1",
                movement_id=str(receipt["id"]),
                policy_code="FIFO",
                input_costs=[{"line_number": 1, "total_cost": "12.34"}],
                actor_label="maker",
            )
            valuation.approve_document(str(document["id"]), reason="Independent review", actor_label="checker")
            delivery = inventory.create_movement(
                movement_number="SHIP-REV-1",
                movement_type="Delivery",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id=f"period-{tenant_a}",
                movement_date="2026-07-28",
                description="Exact compensating movement",
                lines=[{"item_code": "MATERIAL", "quantity": "2.500", "from_location": "MAIN/STOCK"}],
                workspace="Inventory",
                actor_label="maker",
            )
            inventory.post_movement(str(delivery["id"]), reason="Independent review", actor_label="checker")
            reversal = PostgresInventoryValuationReversalRepository(connection, tenant_a)
            cancelled = reversal.create_reversal(
                reversal_number="REV-CANCEL",
                original_valuation_document_id=str(document["id"]),
                reversal_movement_id=str(delivery["id"]),
                actor_label="maker",
            )
            assert reversal.cancel_reversal(
                str(cancelled["id"]), reason="Synthetic cancellation", actor_label="maker"
            )["status"] == "Cancelled"
            draft = reversal.create_reversal(
                reversal_number="REV-1",
                original_valuation_document_id=str(document["id"]),
                reversal_movement_id=str(delivery["id"]),
                actor_label="maker",
            )
            with pytest.raises(PlatformError, match="Segregation of duties"):
                reversal.approve_reversal(str(draft["id"]), reason="Self approval", actor_label="maker")
            approved = reversal.approve_reversal(
                str(draft["id"]), reason="Independent evidence review", actor_label="checker"
            )
            assert approved["status"] == "Approved"
            assert approved["total_value"] == "12.34"
            assert approved["finance_entry_status"] == "Draft"
            assert approved["effects"][0]["effect_type"] == "Remove"
            assert approved["effects"][0]["quantity"] == "2.500"
            assert approved["effects"][0]["value"] == "12.34"
            layers = valuation.list_cost_layers(workspace="Inventory")
            assert layers[0]["remaining_quantity"] == "0.000"
            assert layers[0]["remaining_value"] == "0.00"
            assert valuation.summary(workspace="Inventory").unvalued_posted_movements == 0
            with pytest.raises(PlatformError, match="compensating reversal movement"):
                valuation.create_document(
                    valuation_number="INVALID-NORMAL-VALUATION",
                    movement_id=str(delivery["id"]),
                    policy_code="FIFO",
                )
            with pytest.raises(PlatformError, match="protects its compensating movement"):
                inventory.void_movement(str(delivery["id"]), reason="Invalid void", actor_label="checker")
            summary = reversal.summary(workspace="Inventory")
            assert summary.approved_reversals == 1
            assert summary.cancelled_reversals == 1
            assert summary.approved_effects == 1
            assert summary.finance_drafts == 1
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            reversal = PostgresInventoryValuationReversalRepository(connection, tenant_b)
            assert reversal.list_reversals(workspace="Inventory") == []
            assert reversal.summary(workspace="Inventory").approved_reversals == 0
    finally:
        for tenant in (tenant_a, tenant_b):
            try:
                with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                    connection.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant,))
            except psycopg.Error:
                pass
        admin.close()
