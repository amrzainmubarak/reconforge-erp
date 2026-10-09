"""Exact same-ledger expansion proof and populated native catalog recovery."""
from __future__ import annotations

import hashlib
import subprocess  # nosec B404
from collections.abc import Callable, Sequence
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
from reconforge.infrastructure.postgres_operations import POSTGRES_MIGRATION_REVISIONS
from tests.gfo_browser_restore import FINANCIAL_TABLES, database_snapshot, require
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

EXPANSION_TABLES = (
    "stock_sales_orders", "stock_sales_reservations", "stock_sales_issue_claims", "stock_sales_events", "stock_sales_commands",
    "procurement_partial_orders", "procurement_partial_receipts", "procurement_partial_invoices", "procurement_partial_commands",
    "financial_installment_plans", "financial_installment_reviews", "financial_installment_links", "financial_installment_commands",
    "financial_reporting_maps", "financial_reporting_map_reviews", "financial_opening_plans", "financial_opening_reviews",
    "financial_opening_links", "financial_reporting_commands",
)


def verify_expansion_cycles(runtime: ReceiptRuntime) -> dict[str, Any]:
    with runtime.actor("browser-poster") as (connection, _, actor):
        sale = connection.execute("SELECT * FROM reconforge.stock_sales_orders WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        require(len(sale) == 1 and sale[0]["status"] == "Paid" and sale[0]["total_minor"] == 22500, "Actual product sale did not settle.")
        partial = connection.execute("SELECT * FROM reconforge.procurement_partial_orders WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        require(len(partial) == 1, "Actual partial purchase is absent or duplicated.")
        receipts = connection.execute("SELECT stage FROM reconforge.procurement_partial_receipts WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        invoices = connection.execute("SELECT stage,native_invoice_id FROM reconforge.procurement_partial_invoices WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        require(len(receipts) == 2 and all(row["stage"] == 2 for row in receipts), "Two actual stock tranches must be posted.")
        require(len(invoices) == 2 and all(row["stage"] == 4 for row in invoices), "Two matched invoices must have reviewed accruals.")
        require(connection.execute("SELECT count(*) n FROM reconforge.ap_supplier_invoices WHERE tenant_id=%s AND status='Paid'", (runtime.tenant,)).fetchone()["n"] == 2, "Native AP is not completely settled.")
        require(connection.execute("SELECT count(*) n FROM reconforge.financial_installment_links WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 4, "Four independently reviewed installment effects are required.")
        require(connection.execute("SELECT status FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s", (runtime.tenant, sale[0]["invoice_id"])).fetchone()["status"] == "Paid", "Native customer invoice is not paid.")
        layers = connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s ORDER BY created_at,id", (runtime.tenant,)).fetchall()
        require([dict(row) for row in layers] == [{"remaining_quantity_scaled": 0, "remaining_value_minor": 0}, {"remaining_quantity_scaled": 5, "remaining_value_minor": 6000}], "Exact FIFO depletion and residual value differ.")
        require(connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 12, "Exactly twelve actual posting effects are required.")
        mapping = connection.execute("SELECT id FROM reconforge.financial_reporting_maps WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
        report = PostgresFinancialReportingRepository(connection, runtime.tenant).report(
            map_id=mapping["id"], period_id="period", as_of_date="2026-10-11", organization_code="ORG", entity_code="ENTITY", actor=actor,
        )
        require(report["effect_count"] == 12, "Statements lost a contributing effect.")
        require(report["balance_sheet"] == {"assets_minor": 116500, "liabilities_minor": 0, "equity_minor": 100000, "accumulated_unclosed_result_minor": 16500, "balanced": True}, "Balance sheet does not reproduce source operations.")
        require(report["income_statement"] == {"income_minor": 22500, "expense_minor": 6000, "result_minor": 16500}, "Income statement disagrees with actual revenue and FIFO cost.")
        require(report["cash_movements"]["closing_minor"] == 110500 and report["cash_movements"]["outflow_minor"] == 12000, "Cash movements disagree with reviewed installments and collection.")
        return {"sale_id": sale[0]["id"], "purchase_id": partial[0]["id"], "stock_receipts": 2, "supplier_invoices": 2,
                "payment_installments": 4, "posting_effects": 12, "fifo_residual_quantity": "5", "fifo_residual_minor": "6000", "statements": report}


def verify_expansion_native_restore(runtime: ReceiptRuntime, container: str, *,
        verify_cycles: Callable[[ReceiptRuntime], dict[str, Any]] = verify_expansion_cycles,
        extension_tables: tuple[str, ...] = EXPANSION_TABLES,
        tamper_statements: Sequence[str] = (
            "UPDATE reconforge.stock_sales_orders SET total_minor=total_minor+1,row_version=row_version+1 WHERE tenant_id=%s",
            "UPDATE reconforge.financial_installment_links SET posted_actor_id='maker' WHERE tenant_id=%s",
            "UPDATE reconforge.financial_opening_links SET posted_actor_id='maker' WHERE tenant_id=%s",
        )) -> dict[str, Any]:
    effects = verify_cycles(runtime)
    protected = FINANCIAL_TABLES + extension_tables
    before = database_snapshot(runtime.admin_dsn, financial_tables=protected)
    require(before["head"] == POSTGRES_MIGRATION_REVISIONS[-1], "Expansion restore is not current migration head.")
    dump = subprocess.run(["docker", "exec", container, "pg_dump", "--username=postgres", "--dbname=postgres", "--format=custom"], capture_output=True, check=True, timeout=120)  # nosec B603 B607
    require(dump.stdout.startswith(b"PGDMP"), "Actual PostgreSQL dump is absent.")
    database = "erp_expand_restore_" + uuid4().hex[:12]
    admin_dsn = psycopg.conninfo.make_conninfo(runtime.admin_dsn, dbname=database)
    app_dsn = psycopg.conninfo.make_conninfo(runtime.factory.settings.dsn, dbname=database)
    try:
        with psycopg.connect(runtime.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database)))
        subprocess.run(["docker", "exec", "-i", container, "pg_restore", "--username=postgres", "--exit-on-error", f"--dbname={database}"], input=dump.stdout, capture_output=True, check=True, timeout=180)  # nosec B603 B607
        after = database_snapshot(admin_dsn, financial_tables=protected)
        require(before == after, "Full populated rows/catalog/ACL/RLS changed during native restore.")
        restored = ReceiptRuntime(PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False)), admin_dsn, runtime.tenant, runtime.password)
        require(effects == verify_cycles(restored), "Restored source and financial effects differ.")
        with psycopg.connect(app_dsn) as connection:
            flags = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            require(flags is not None and list(flags) == [False, False], "Restore role bypasses isolation.")
            for table in extension_tables:
                rows = connection.execute(sql.SQL("SELECT count(*) FROM reconforge.{}").format(sql.Identifier(table))).fetchone()
                require(rows is not None and rows[0] == 0, "Unbound native read leaked.")
        with PostgresTenantBoundary(restored.factory).transaction(runtime.tenant, workspace_id="foreign", organization_id="org", legal_entity_id="entity") as connection:
            for table in extension_tables:
                require(connection.execute(sql.SQL("SELECT count(*) n FROM reconforge.{}").format(sql.Identifier(table))).fetchone()["n"] == 0, "Sibling workspace leaked after restore.")
        refused = 0
        with restored.actor("browser-poster") as (connection, _, _actor):
            checkpoint = database_snapshot(admin_dsn, financial_tables=protected)
            for statement in tamper_statements:
                try:
                    with connection.transaction():
                        connection.execute(statement, (runtime.tenant,))
                except psycopg.errors.CheckViolation:
                    refused += 1
        require(refused == len(tamper_statements) and checkpoint == database_snapshot(admin_dsn, financial_tables=protected), "Restored immutable guards or exact rollback are absent.")
        return {"status": "passed", "dump_sha256": hashlib.sha256(dump.stdout).hexdigest(), "snapshot": after,
                "probe_checkpoint": checkpoint, "verified_effects": effects, "tamper_refusals": refused}
    finally:
        with psycopg.connect(runtime.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            require(admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None, "Owned restore database remains.")
