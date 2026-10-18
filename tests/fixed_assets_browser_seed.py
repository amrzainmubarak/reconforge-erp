"""Canonical masters only; all source asset and financial writes use Studio."""

from typing import Any

from reconforge.infrastructure.postgres_fixed_assets import PostgresFixedAssetsRepository
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.gfo_browser_restore import require
from tests.gfo_receipt_browser_seed import seed_receipt_browser
from tests.test_postgres_fixed_assets import seed_asset_masters
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

FIXED_ASSET_TABLES = ("fixed_assets", "fixed_asset_plans", "fixed_asset_reviews", "fixed_asset_links", "fixed_asset_commands")


def seed_fixed_assets_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    runtime = seed_receipt_browser(admin_dsn, app_dsn)
    seed_asset_masters(runtime)
    seed_erp_browser_principals(runtime)
    return runtime


def verify_fixed_assets_browser(runtime: ReceiptRuntime) -> dict[str, Any]:
    """Expected integer amounts are independent of the depreciation implementation."""
    with runtime.actor("browser-poster") as (connection, _, actor):
        assets = connection.execute("SELECT id FROM reconforge.fixed_assets WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        require(len(assets) == 1, "The browser acquisition was lost or duplicated.")
        detail = PostgresFixedAssetsRepository(connection, runtime.tenant).get(assets[0]["id"], actor=actor)
        require(detail["asset_number"] == "BROWSER-ASSET" and detail["status"] == "Disposed" and detail["carrying_minor"] == 0, "Actual asset disposal did not complete.")
        require([row["kind"] for row in detail["plans"]] == ["acquire", "depreciate", "depreciate", "dispose"], "Actual acquisition, two depreciation tranches and disposal are required.")
        require([row["amount_minor"] for row in detail["plans"]] == [10101, 3033, 6067, 1001], "Exact independent historical cost and cumulative entitlement oracle differs.")
        require(detail["months"] == 3 and detail["accumulated_minor"] == 9100, "Final service months and historical depreciation differ.")
        require(all(row["status"] == "Posted" and row["preparer_actor_id"] == "erp-maker" and row["reviewer_actor_id"] == "erp-checker" for row in detail["plans"]), "Actual independent browser preparation and review provenance differs.")
        links = connection.execute("SELECT posted_actor_id FROM reconforge.fixed_asset_links WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        require(len(links) == 4 and all(row["posted_actor_id"] == "erp-poster" for row in links), "Four native effects require the independent third human.")
        balances = connection.execute("""SELECT account.account_code,sum(line.debit_minor-line.credit_minor)::bigint AS amount
            FROM reconforge.finance_posting_effects effect JOIN reconforge.finance_entry_lines line ON line.tenant_id=effect.tenant_id AND line.entry_id=effect.entry_id
            JOIN reconforge.finance_accounts account ON account.tenant_id=line.tenant_id AND account.id=line.account_id
            WHERE effect.tenant_id=%s GROUP BY account.account_code""", (runtime.tenant,)).fetchall()
        expected = {"FIXED": 0, "ACCUM": 0, "DEPRECIATION": 9100, "CASH": -8601, "GAIN": -499}
        actual = {row["account_code"]: row["amount"] for row in balances}
        require(actual == expected and sum(actual.values()) == 0, "Actual native GL differs from the independent acquisition, expense, proceeds and gain equation.")
        return {"asset_id": detail["id"], "asset_status": "Disposed", "source_plans": 4, "native_posting_effects": 4,
                "cost_minor": "10101", "depreciation_tranches_minor": ["3033", "6067"], "accumulated_minor": "9100",
                "disposal_carrying_minor": "1001", "proceeds_minor": "1500", "gain_minor": "499", "final_carrying_minor": "0",
                "account_balances_minor": {key: str(value) for key, value in expected.items()}}
