"""Verify completed browser Sales and Procurement against the same real ledger."""
from __future__ import annotations

import hashlib
import subprocess  # nosec B404
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_operations import POSTGRES_MIGRATION_REVISIONS
from tests.gfo_browser_restore import FINANCIAL_TABLES, database_snapshot, require
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

ERP_TABLES = (
    "operational_finance_plans", "operational_finance_reviews", "operational_finance_links", "operational_finance_commands",
    "sales_revenue_documents", "sales_revenue_events", "sales_revenue_commands", "procurement_cycles", "procurement_commands",
)


def verify_cycles(runtime: ReceiptRuntime) -> dict[str, Any]:
    with runtime.actor("browser-poster") as (connection, _, actor):
        sale = connection.execute("SELECT * FROM reconforge.sales_revenue_documents WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
        purchase = connection.execute("SELECT * FROM reconforge.procurement_cycles WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
        require(sale is not None and sale["status"] == "Paid" and sale["total_minor"] == 9800, "Browser sale is incomplete.")
        require(purchase is not None and purchase["stage"] == 13 and purchase["total_minor"] == 12000, "Browser purchase is incomplete.")
        require(connection.execute("SELECT count(*) n FROM reconforge.sales_revenue_documents WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1, "Duplicate sale.")
        require(connection.execute("SELECT count(*) n FROM reconforge.procurement_cycles WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1, "Duplicate purchase.")
        ar = connection.execute("SELECT status FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s", (runtime.tenant, sale["invoice_id"])).fetchone()
        ap = connection.execute("SELECT status FROM reconforge.ap_supplier_invoices WHERE tenant_id=%s AND id=%s", (runtime.tenant, purchase["invoice_id"])).fetchone()
        require(ar["status"] == "Paid" and ap["status"] == "Paid", "Native AR/AP must both be settled.")
        require(connection.execute("SELECT c.customer_code FROM reconforge.ar_customers c JOIN reconforge.ar_invoices i ON i.tenant_id=c.tenant_id AND i.customer_id=c.id WHERE i.tenant_id=%s AND i.id=%s", (runtime.tenant, sale["invoice_id"])).fetchone()["customer_code"] == "BROWSER-CUSTOMER", "Sale did not use the browser-created customer.")
        require(connection.execute("SELECT s.supplier_code FROM reconforge.ap_suppliers s JOIN reconforge.ap_supplier_invoices i ON i.tenant_id=s.tenant_id AND i.supplier_id=s.id WHERE i.tenant_id=%s AND i.id=%s", (runtime.tenant, purchase["invoice_id"])).fetchone()["supplier_code"] == "BROWSER-SUPPLIER", "Purchase did not use the browser-created supplier.")
        require(connection.execute("SELECT count(*) n FROM reconforge.ar_receipt_allocations WHERE tenant_id=%s AND invoice_id=%s", (runtime.tenant, sale["invoice_id"])).fetchone()["n"] == 1, "Collection repeated.")
        require(connection.execute("SELECT count(*) n FROM reconforge.ap_payment_links WHERE tenant_id=%s AND supplier_invoice_id=%s", (runtime.tenant, purchase["invoice_id"])).fetchone()["n"] == 1, "Payment repeated.")
        layers = connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        require(len(layers) == 1 and dict(layers[0]) == {"remaining_quantity_scaled": 10, "remaining_value_minor": 12000}, "Stock and FIFO differ.")
        links = connection.execute("SELECT p.source_kind,p.source_id,p.amount_minor,l.posting_effect_id,p.preparer_actor_id,r.reviewer_actor_id,l.posted_actor_id FROM reconforge.operational_finance_plans p JOIN reconforge.operational_finance_reviews r ON r.tenant_id=p.tenant_id AND r.plan_id=p.id JOIN reconforge.operational_finance_links l ON l.tenant_id=p.tenant_id AND l.plan_id=p.id WHERE p.tenant_id=%s ORDER BY p.source_kind", (runtime.tenant,)).fetchall()
        require(len(links) == 4 and all(row["preparer_actor_id"] != row["reviewer_actor_id"] and row["preparer_actor_id"] != row["posted_actor_id"] for row in links), "Source review or publication is incomplete.")
        trial = PostgresFinancePostingRepository(connection, runtime.tenant).posted_trial_balance(period_id="period", organization_code="ORG", entity_code="ENTITY", workspace="work", actor=actor)
        require(trial["balance_totals"] == {"debit_minor": 12000, "credit_minor": 12000, "balanced": True}, "Shared ledger net balances differ.")
        effect_count = connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"]
        require(effect_count == 5, "Exactly five reviewed ledger effects are required.")
        return {"sale_id": sale["id"], "purchase_id": purchase["id"], "sale_minor": "9800", "purchase_minor": "12000",
                "native_ar_status": ar["status"], "native_ap_status": ap["status"], "source_finance_links": 4,
                "posting_effects": effect_count, "stock_quantity_scaled": "10", "fifo_value_minor": "12000", "trial_balance": trial}


def verify_erp_native_restore(runtime: ReceiptRuntime, container: str) -> dict[str, Any]:
    before_effects = verify_cycles(runtime)
    before = database_snapshot(runtime.admin_dsn, financial_tables=FINANCIAL_TABLES + ERP_TABLES)
    require(before["head"] == POSTGRES_MIGRATION_REVISIONS[-1], "Restore source is not the current schema.")
    dump = subprocess.run(["docker", "exec", container, "pg_dump", "--username=postgres", "--dbname=postgres", "--format=custom"], capture_output=True, check=True, timeout=120)  # nosec B603 B607
    require(dump.stdout.startswith(b"PGDMP"), "Native dump was not produced.")
    database = "erp_browser_restore_" + uuid4().hex[:12]
    admin_dsn = psycopg.conninfo.make_conninfo(runtime.admin_dsn, dbname=database)
    app_dsn = psycopg.conninfo.make_conninfo(runtime.factory.settings.dsn, dbname=database)
    created = False
    try:
        with psycopg.connect(runtime.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database)))
            created = True
        subprocess.run(["docker", "exec", "-i", container, "pg_restore", "--username=postgres", "--exit-on-error", f"--dbname={database}"], input=dump.stdout, capture_output=True, check=True, timeout=180)  # nosec B603 B607
        after = database_snapshot(admin_dsn, financial_tables=FINANCIAL_TABLES + ERP_TABLES)
        require(before == after, "Populated rows, schemas, policies or ACLs changed during native recovery.")
        restored = ReceiptRuntime(PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False)), admin_dsn, runtime.tenant, runtime.password)
        require(before_effects == verify_cycles(restored), "Restored operational or ledger state differs.")
        with psycopg.connect(app_dsn) as connection:
            require(list(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == [False, False], "Recovery role bypasses RLS.")
            require(connection.execute("SELECT count(*) FROM reconforge.sales_revenue_documents").fetchone()[0] == 0, "Unbound Sales read leaked.")
        with PostgresTenantBoundary(restored.factory).transaction(runtime.tenant, workspace_id="foreign", organization_id="org", legal_entity_id="entity") as connection:
            for table in ERP_TABLES:
                require(connection.execute(sql.SQL("SELECT count(*) n FROM reconforge.{}").format(sql.Identifier(table))).fetchone()["n"] == 0, "Sibling workspace leaked after recovery.")
        refused = 0
        with restored.actor("browser-poster") as (connection, _, _):
            # Authentication legitimately updates identity metadata in its own
            # committed transaction. Keep the exact restored snapshot above;
            # compare refused writes against a complete post-authentication
            # checkpoint without removing identity or audit tables.
            probe_checkpoint = database_snapshot(admin_dsn, financial_tables=FINANCIAL_TABLES + ERP_TABLES)
            for statement in (
                "UPDATE reconforge.operational_finance_links SET posted_actor_id='maker' WHERE tenant_id=%s",
                "UPDATE reconforge.sales_revenue_documents SET total_minor=total_minor+1,row_version=row_version+1 WHERE tenant_id=%s",
                "UPDATE reconforge.procurement_cycles SET total_minor=total_minor+1,row_version=row_version+1 WHERE tenant_id=%s",
            ):
                try:
                    with connection.transaction():
                        connection.execute(statement, (runtime.tenant,))
                except psycopg.errors.CheckViolation:
                    refused += 1
        require(refused == 3, "A restored immutable financial guard was absent.")
        require(probe_checkpoint == database_snapshot(admin_dsn, financial_tables=FINANCIAL_TABLES + ERP_TABLES), "Rejected recovery probes changed data.")
        return {"status": "passed", "dump_sha256": hashlib.sha256(dump.stdout).hexdigest(), "snapshot": after,
                "probe_checkpoint": probe_checkpoint, "verified_effects": before_effects, "tamper_refusals": refused}
    finally:
        if created:
            with psycopg.connect(runtime.admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
                require(admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None, "Owned restored database was not removed.")
