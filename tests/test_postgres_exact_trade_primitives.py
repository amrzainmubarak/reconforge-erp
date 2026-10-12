"""Exact trade arithmetic on a migrated database using a nonowner runtime role."""

from __future__ import annotations

import os
from decimal import ROUND_DOWN, ROUND_UP, Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest

from reconforge.application.receivables import ReceivableInvoiceLineInput
from reconforge.infrastructure.postgres import (
    PostgresRuntimePooledConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_inventory_valuation import PostgresInventoryValuationRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.platform.common import PlatformError
from tests.test_alembic_postgres import isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn

isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn
TENANT = "exact_trade_synthetic"


@pytest.fixture
def trade_database(isolated_postgres_migration_dsn: str):
    import psycopg
    from alembic.config import Config

    from alembic import command

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("PROD035 requires the live PostgreSQL nonowner profile; review 2026-10-03")
    command.upgrade(Config(str(Path("alembic.ini").resolve())), "head")
    params = psycopg.conninfo.conninfo_to_dict(app_dsn)
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)["dbname"]
    with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
        role = psycopg.sql.Identifier(params["user"])
        admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}").format(role))
        admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,'Synthetic exact trade')", (TENANT,))
        admin.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,'exact','Exact')", (TENANT,))
        admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,'USD','Synthetic',2)", (TENANT,))
        admin.execute("INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,application_workspace_id) VALUES(%s,'org','SYN','Synthetic','USD','exact')", (TENANT,))
        admin.execute("INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) VALUES(%s,'exact','org')", (TENANT,))
        admin.execute("INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES(%s,'entity','org','E1','Synthetic','USD')", (TENANT,))
        admin.execute("INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number,application_workspace_id) VALUES(%s,'period','July','2026-07-01','2026-07-31',2026,7,'exact')", (TENANT,))
        admin.execute("INSERT INTO reconforge.master_data_workspace_periods(tenant_id,workspace_id,period_id) VALUES(%s,'exact','period')", (TENANT,))
    factory = PostgresRuntimePooledConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**params), require_tls=False), max_size=2)
    boundary = PostgresTenantBoundary(factory)
    try:
        with boundary.transaction(TENANT) as connection:
            assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
            finance = PostgresFinanceCoreRepository(connection, TENANT)
            finance.upsert_chart(chart_code="DEFAULT", name="Default", workspace="Exact", organization_code="SYN")
            for account, kind in (("STOCK", "Asset"), ("GRNI", "Liability"), ("COGS", "Expense"), ("ADJUST", "Expense")):
                finance.upsert_account(account_code=account, name=account, account_type=kind, workspace="Exact")
            finance.upsert_journal(journal_code="INV", name="Inventory", organization_code="SYN", currency_code="USD", workspace="Exact")
            inventory = PostgresInventoryCoreRepository(connection, TENANT)
            inventory.upsert_uom(uom_code="KG", name="Kilogram", category="Weight", decimal_places=3, workspace="Exact")
            inventory.upsert_item(item_code="ITEM", name="Item", organization_code="SYN", uom_code="KG", inventory_account_code="STOCK", workspace="Exact")
            inventory.upsert_warehouse(warehouse_code="MAIN", name="Main", organization_code="SYN", entity_code="E1", workspace="Exact")
            inventory.upsert_location(warehouse_code="MAIN", location_code="STOCK", name="Stock", organization_code="SYN", workspace="Exact")
            PostgresInventoryValuationRepository(connection, TENANT).upsert_policy(policy_code="FIFO", organization_code="SYN", entity_code="E1", journal_code="INV", receipt_clearing_account_code="GRNI", cogs_account_code="COGS", adjustment_account_code="ADJUST", workspace="Exact")
            PostgresReceivablesRepository(connection, TENANT).upsert_customer(customer_code="CUS", name="Customer", currency_code="USD", credit_limit_minor=0, workspace="Exact")
        yield boundary
    finally:
        factory.close()


def _value(boundary: Any, number: str, quantity: str, cost: str | None) -> dict[str, Any]:
    with boundary.transaction(TENANT) as connection:
        inventory = PostgresInventoryCoreRepository(connection, TENANT)
        movement = inventory.create_movement(
            movement_number=number, movement_type="Receipt" if cost is not None else "Delivery",
            organization_code="SYN", entity_code="E1", period_id="period", movement_date="2026-07-01" if cost is not None else "2026-07-02",
            description="Synthetic exact quantity", workspace="Exact", actor_label="maker",
            lines=[{"item_code": "ITEM", "quantity": quantity, "to_location" if cost is not None else "from_location": "MAIN/STOCK"}],
        )
        inventory.post_movement(movement["id"], reason="Independent stock review", actor_label="checker")
        valuation = PostgresInventoryValuationRepository(connection, TENANT)
        document = valuation.create_document(valuation_number=f"VAL-{number}", movement_id=movement["id"], policy_code="FIFO", input_costs=[] if cost is None else [{"line_number": 1, "total_cost": cost}], actor_label="maker")
        return valuation.approve_document(document["id"], reason="Independent cost review", actor_label="checker")


@pytest.mark.parametrize("rounding", [ROUND_DOWN, ROUND_UP])
def test_live_exact_quantities_ar_product_fifo_layers_and_final_residual(trade_database: Any, rounding: str) -> None:
    boundary = trade_database
    raw = "123456789012345678.123456789012345"
    with localcontext() as context:
        context.prec = 2
        context.rounding = rounding
        context.Emax = 2
        context.Emin = -2
        for signal in context.traps:
            context.traps[signal] = True
        with boundary.transaction(TENANT) as connection:
            ar = PostgresReceivablesRepository(connection, TENANT)
            invoice = ar.create_invoice(invoice_number="EXACT-AR", customer_code="CUS", invoice_date="2026-07-01", currency_code="USD", tax_minor=0, workspace="Exact", actor_label="maker", lines=[ReceivableInvoiceLineInput("Exact", raw, 1, 123456789012345678), ReceivableInvoiceLineInput("Half up", "0.5", 5, 3)])
        with boundary.transaction(TENANT) as connection:
            persisted = PostgresReceivablesRepository(connection, TENANT).get_invoice(invoice["id"])
            assert persisted["total_minor"] == 123456789012345681
            assert persisted["lines"][0]["quantity"] == raw
            row = connection.execute("SELECT quantity,quantity_text FROM reconforge.ar_invoice_lines WHERE invoice_id=%s AND line_number=1", (invoice["id"],)).fetchone()
            assert tuple(row) == (Decimal(raw), raw)
            before = tuple(connection.execute("SELECT (SELECT count(*) FROM reconforge.ar_invoices),(SELECT count(*) FROM reconforge.domain_audit_events),(SELECT count(*) FROM reconforge.outbox_events)").fetchone())
            for invalid in ("1e2", Decimal("1E+1000000"), Decimal("1E-1000000")):
                with pytest.raises(PlatformError):
                    PostgresReceivablesRepository(connection, TENANT).create_invoice(invoice_number="INVALID", customer_code="CUS", invoice_date="2026-07-01", currency_code="USD", tax_minor=0, workspace="Exact", lines=[ReceivableInvoiceLineInput("Invalid", invalid, 1, 100)])
                assert tuple(connection.execute("SELECT (SELECT count(*) FROM reconforge.ar_invoices),(SELECT count(*) FROM reconforge.domain_audit_events),(SELECT count(*) FROM reconforge.outbox_events)").fetchone()) == before
        _value(boundary, "RCV-1", "3.000", "1.99")
        _value(boundary, "RCV-2", "2.000", "1.01")
        issues = [_value(boundary, f"OUT-{number}", quantity, None) for number, quantity in ((1, "1.000"), (2, "3.000"), (3, "1.000"))]
        assert [issue["total_value"] for issue in issues] == ["0.66", "1.83", "0.51"]
        assert [[line["value"] for line in issue["layer_consumptions"]] for issue in issues] == [["0.66"], ["1.33", "0.50"], ["0.51"]]
        with boundary.transaction(TENANT) as connection:
            layers = PostgresInventoryValuationRepository(connection, TENANT).list_cost_layers(workspace="Exact", open_only=False)
            assert len(layers) == 2
            assert all(layer["remaining_quantity"] == "0.000" and layer["remaining_value"] == "0.00" for layer in layers)
            assert connection.execute("SELECT sum(value_minor) FROM reconforge.inventory_layer_consumptions").fetchone()[0] == 300
