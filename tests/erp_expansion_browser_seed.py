"""Canonical masters only; all expansion source and financial writes use Studio."""

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.gfo_receipt_browser_seed import seed_receipt_browser
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_procurement_operations import seed_procurement
from tests.test_postgres_stock_sales import create_stock_runtime


def seed_expansion_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    runtime = seed_receipt_browser(admin_dsn, app_dsn)
    create_stock_runtime((admin_dsn, app_dsn), base_runtime=runtime, seed_stock=False)
    seed_procurement(runtime)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org") as connection:
        PostgresFinanceCoreRepository(connection, runtime.tenant).upsert_account(
            account_code="EQUITY", name="Initial equity", account_type="Equity", normal_balance="Credit",
            chart_code="DEFAULT", workspace="work",
        )
    seed_erp_browser_principals(runtime)
    with runtime.actor("browser-maker") as (connection, _, _actor):
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
    return runtime
