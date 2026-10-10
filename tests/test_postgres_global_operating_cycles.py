"""One tenant, actual landed stock/AP/cash/AR/assets and independent reporting oracle."""
from __future__ import annotations

from fractions import Fraction
from typing import Any

import pytest

from reconforge.domain.commercial_collections import CommercialCollectionPreparation
from reconforge.domain.financial_reporting import AccountClassification, OpeningLine, OpeningPreparation, ReportingScope
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_commercial_collections import PostgresCommercialCollectionsRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
from reconforge.infrastructure.postgres_fixed_assets import PostgresFixedAssetsRepository
from reconforge.infrastructure.postgres_landed_cost import PostgresLandedCostRepository
from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
from tests.test_postgres_commercial_collections import complete as collect
from tests.test_postgres_commercial_collections import phase as collection_phase
from tests.test_postgres_commercial_collections import prepare as prepare_collection
from tests.test_postgres_financial_reporting import post_opening
from tests.test_postgres_fixed_assets import acquire, finish, operation, seed_asset_masters
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_landed_cost import phase as landed_phase
from tests.test_postgres_landed_cost import prepare as prepare_landed
from tests.test_postgres_landed_cost import request as landed_request
from tests.test_postgres_procurement_multiline import (
    CHECKER,
    POSTER,
    accrue_invoice,
    create_multiline_runtime,
    create_order,
    pay_invoice,
    pytestmark,
    receipt_database,
)
from tests.test_postgres_stock_sales import create_reserved_order, create_stock_runtime, execute

__all__ = ["pytestmark", "receipt_database"]


def independent_allocation(amount: int, bases: tuple[int, ...]) -> tuple[int, ...]:
    """Independent rational oracle; largest remainder without production helpers."""
    quotas = tuple(Fraction(amount * base, sum(bases)) for base in bases)
    allocated = [quota.numerator // quota.denominator for quota in quotas]
    order = sorted(range(len(bases)), key=lambda index: (-(quotas[index] - allocated[index]), index))
    for index in order[:amount - sum(allocated)]:
        allocated[index] += 1
    return tuple(allocated)


def reviewed_reporting_map(runtime: ReceiptRuntime) -> dict[str, Any]:
    classifications = {
        "INVENTORY": "CurrentAsset", "CASH": "CurrentAsset", "AR": "CurrentAsset",
        "FIXED": "NonCurrentAsset", "ACCUM": "NonCurrentAsset", "CLEARING": "CurrentLiability",
        "AP": "CurrentLiability", "COGS": "Expense", "DEPRECIATION": "Expense",
        "REVENUE": "Income", "GAIN": "Income", "EQUITY": "Equity",
    }
    with runtime.actor("maker") as (connection, _, actor):
        prepared = PostgresFinancialReportingRepository(connection, runtime.tenant).prepare_map(
            ReportingScope("work", "org", "entity"), name="Actual integrated operating chart",
            accounts=[AccountClassification(code, section, code == "CASH") for code, section in classifications.items()],
            command_id="global-map-prepare", actor=actor)
    with runtime.actor("checker") as (connection, _, actor):
        return PostgresFinancialReportingRepository(connection, runtime.tenant).review_map(
            prepared["id"], expected_digest=prepared["map_digest"], reason="Independent global chart classification",
            command_id="global-map-review", actor=actor)


@pytest.mark.parametrize("abandon_reviewed_claims", [False, True])
def test_paid_landed_stock_partial_ar_assets_and_native_statements_share_one_financial_truth(
    receipt_database: tuple[str, str], abandon_reviewed_claims: bool,
) -> None:
    runtime = create_multiline_runtime(receipt_database)
    runtime = create_stock_runtime(receipt_database, base_runtime=runtime, seed_stock=False)
    seed_asset_masters(runtime)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        PostgresFinanceCoreRepository(connection, runtime.tenant).upsert_account(
            account_code="EQUITY", name="Opening paid capital", account_type="Equity", normal_balance="Credit",
            chart_code="DEFAULT", workspace="work")
    mapping = reviewed_reporting_map(runtime)
    with runtime.actor("maker") as (connection, _, actor):
        funding = PostgresFinancialReportingRepository(connection, runtime.tenant).prepare_opening(
            OpeningPreparation(ReportingScope("work", "org", "entity"), mapping["id"], "ORG", "ENTITY", "period", "STOCK",
                "2026-10-01", "Governed paid opening capital before purchasing",
                (OpeningLine("CASH", 50000, 0), OpeningLine("EQUITY", 0, 50000))),
            command_id="global-funding-prepare", actor=actor)
    with runtime.actor("checker") as (connection, _, actor):
        funding = PostgresFinancialReportingRepository(connection, runtime.tenant).review_opening(
            funding["id"], expected_digest=funding["plan_digest"], reason="Independent opening funding review",
            command_id="global-funding-review", actor=actor)
    assert post_opening(runtime, funding)["status"] == "Posted"
    purchase = create_order(runtime, "GLOBAL-SUPPLY")
    landed = prepare_landed(runtime, purchase)
    if abandon_reviewed_claims:
        with runtime.actor(CHECKER) as (connection, _, actor):
            landed = PostgresLandedCostRepository(connection, runtime.tenant).act(
                landed["id"], "review", expected_plan_digest=landed["plan_digest"], command_id="global-lc-abandoned-review",
                reason="Independently review receipt that will retain abandonment evidence", actor=actor)
        with runtime.actor(POSTER) as (connection, _, actor):
            owner = PostgresLandedCostRepository(connection, runtime.tenant)
            args = {"expected_plan_digest": landed["plan_digest"], "command_id": "global-lc-cancel",
                    "reason": "Retain reviewed abandoned receipt evidence before safe replacement", "actor": actor}
            cancelled_landed = owner.cancel(landed["id"], **args)
            assert cancelled_landed["status"] == "Cancelled"
            assert owner.cancel(landed["id"], **args) == cancelled_landed
            assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 1
            assert connection.execute("SELECT count(*) FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 0
            purchase = PostgresProcurementPartialRepository(connection, runtime.tenant).get(purchase["order"]["id"], actor=actor)
        with runtime.actor("maker") as (connection, _, actor):
            landed = PostgresLandedCostRepository(connection, runtime.tenant).prepare(
                landed_request(purchase, number="GLOBAL-LC-REPLACEMENT"), command_id="global-lc-replacement", actor=actor)
    landed = landed_phase(runtime, landed_phase(runtime, landed, "review", CHECKER), "post", POSTER)
    freight = independent_allocation(777, (12000, 5000))
    duties = independent_allocation(224, (12000, 5000))
    item_value = 12000 + freight[0] + duties[0]
    weighted_value = 5000 + freight[1] + duties[1]
    assert (freight, duties, item_value, weighted_value) == ((548, 229), (158, 66), 12706, 5295)
    with runtime.actor(POSTER) as (connection, _, actor):
        purchase = PostgresProcurementPartialRepository(connection, runtime.tenant).get(purchase["order"]["id"], actor=actor)
    purchase = accrue_invoice(runtime, purchase, ((0, "4"), (1, "1")))
    for amount, suffix in ((3000, "global-ap-1"), (3800, "global-ap-2")):
        pay_invoice(runtime, purchase["invoices"][-1]["native_invoice_id"], amount, suffix)
    purchase = accrue_invoice(runtime, purchase, ((0, "6"), (1, "1.5")))
    for amount, suffix in ((5000, "global-ap-3"), (5200, "global-ap-4")):
        pay_invoice(runtime, purchase["invoices"][-1]["native_invoice_id"], amount, suffix)

    sale = create_reserved_order(runtime, "GLOBAL-SALE", quantity="5")
    for action, human, parameters in (
        ("prepare-issue", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"}),
        ("review-issue", "checker", {}), ("deliver", "poster", {}),
        ("prepare-invoice", "maker", {"invoice_number": "GLOBAL-REVENUE", "invoice_date": "2026-10-09", "due_date": "2026-10-31",
            "journal_code": "SALES", "period_id": "period", "receivable_account_code": "AR", "revenue_account_code": "REVENUE"}),
        ("review-invoice", "checker", {}), ("invoice", "poster", {}),
    ):
        sale = execute(runtime, sale, action, human, parameters)
    cogs = int(Fraction(item_value * 5, 10))
    revenue = 5 * 5000 * (10000 - 1000) // 10000
    first_plan = prepare_collection(runtime, sale["invoice_id"], 9000, "GLOBAL-1")
    if abandon_reviewed_claims:
        first_plan = collection_phase(runtime, first_plan, "review", "checker", "global-ar-abandoned-review")
        cancelled_collection = collection_phase(runtime, first_plan, "cancel", "poster", "global-ar-cancel")
        assert cancelled_collection["status"] == "Cancelled"
        with runtime.actor("maker") as (connection, _, actor):
            replacement = CommercialCollectionPreparation(workspace_id="work", organization_id="org", legal_entity_id="entity",
                organization_code="ORG", entity_code="ENTITY", source_id=sale["invoice_id"], journal_code="CASH", period_id="period",
                posting_date="2026-10-10", debit_account_code="CASH", credit_account_code="AR", reason="Replace abandoned collection without changing actual receipt",
                amount_minor=9000, receipt_number="PARTIAL-CASH-GLOBAL-1")
            first_plan = PostgresCommercialCollectionsRepository(connection, runtime.tenant).prepare(
                replacement, command_id="global-ar-replacement", actor=actor)
    first = collect(runtime, first_plan, "global-ar-1")
    with runtime.actor("maker") as (connection, _, _):
        invoice = connection.execute("SELECT status FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s", (runtime.tenant, sale["invoice_id"])).fetchone()
        assert invoice["status"] == "PartiallyPaid"
    second = collect(runtime, prepare_collection(runtime, sale["invoice_id"], revenue - 9000, "GLOBAL-2"), "global-ar-2")
    assert first["posting_effect_id"] != second["posting_effect_id"]

    asset = finish(runtime, acquire(runtime))
    depreciation_first = finish(runtime, operation(runtime, asset["asset_id"], kind="depreciate", date="2026-11-01", period="nov", month="2026-10"))
    depreciation_rest = finish(runtime, operation(runtime, asset["asset_id"], kind="depreciate", date="2027-01-01", period="jan", month="2026-12"))
    disposed = finish(runtime, operation(runtime, asset["asset_id"], kind="dispose", date="2027-01-02", period="jan", proceeds=1500))
    assert (depreciation_first["amount_minor"], depreciation_rest["amount_minor"], disposed["amount_minor"]) == (3033, 6067, 1001)
    expected = {"AP": 0, "CLEARING": 0, "INVENTORY": item_value - cogs + weighted_value,
        "CASH": 50000 + revenue - (12000 + 5000 + 777 + 224) - 10101 + 1500, "AR": 0, "EQUITY": -50000,
        "COGS": cogs, "REVENUE": -revenue, "FIXED": 0, "ACCUM": 0, "DEPRECIATION": 9100, "GAIN": -499}
    assert sum(expected.values()) == 0
    with runtime.actor("poster") as (connection, _, actor):
        assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
        actual = connection.execute("""SELECT a.account_code,sum((x->>'debit_minor')::bigint-(x->>'credit_minor')::bigint) amount
            FROM reconforge.finance_posting_effects f CROSS JOIN LATERAL jsonb_array_elements(f.snapshot_json->'lines') x
            JOIN reconforge.finance_accounts a ON a.tenant_id=f.tenant_id AND a.id=x->>'account_id'
            WHERE f.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()
        assert {row["account_code"]: int(row["amount"]) for row in actual} == expected
        turnover = connection.execute("""SELECT sum((x->>'debit_minor')::bigint) debit,sum((x->>'credit_minor')::bigint) credit
            FROM reconforge.finance_posting_effects f CROSS JOIN LATERAL jsonb_array_elements(f.snapshot_json->'lines') x WHERE f.tenant_id=%s""", (runtime.tenant,)).fetchone()
        assert tuple(turnover) == (184156, 184156)
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 18
        layers = connection.execute("""SELECT i.item_code,l.remaining_quantity_scaled,l.remaining_value_minor FROM reconforge.inventory_cost_layers l
            JOIN reconforge.inventory_items i ON i.tenant_id=l.tenant_id AND i.id=l.item_id WHERE l.tenant_id=%s ORDER BY i.item_code""", (runtime.tenant,)).fetchall()
        assert [tuple(row) for row in layers] == [("ITEM", 5, 6353), ("WEIGHT", 250, 5295)]
        assert PostgresLandedCostRepository(connection, runtime.tenant).get(landed["id"], actor=actor)["status"] == "Posted"
        if abandon_reviewed_claims:
            assert PostgresLandedCostRepository(connection, runtime.tenant).get(cancelled_landed["id"], actor=actor)["status"] == "Cancelled"
            assert PostgresCommercialCollectionsRepository(connection, runtime.tenant).get(cancelled_collection["id"], actor=actor)["status"] == "Cancelled"
        assert PostgresFixedAssetsRepository(connection, runtime.tenant).get(asset["asset_id"], actor=actor)["status"] == "Disposed"
        supplier = PostgresProcurementPartialRepository(connection, runtime.tenant).get(purchase["order"]["id"], actor=actor)
        assert supplier["totals"]["paid_minor"] == "17000" and supplier["totals"]["outstanding_minor"] == "0"
        reporting = PostgresFinancialReportingRepository(connection, runtime.tenant)
        october = reporting.report(map_id=mapping["id"], period_id="period", as_of_date="2026-10-31", organization_code="ORG", entity_code="ENTITY", actor=actor)
        january = reporting.report(map_id=mapping["id"], period_id="jan", as_of_date="2027-01-02", organization_code="ORG", entity_code="ENTITY", actor=actor)
        assert october["income_statement"] == {"income_minor": 22500, "expense_minor": 6353, "result_minor": 16147}
        assert october["balance_sheet"] == {"assets_minor": 66147, "liabilities_minor": 0, "equity_minor": 50000, "accumulated_unclosed_result_minor": 16147, "balanced": True}
        assert january["income_statement"] == {"income_minor": 499, "expense_minor": 6067, "result_minor": -5568}
        assert january["balance_sheet"] == {"assets_minor": 57546, "liabilities_minor": 0, "equity_minor": 50000, "accumulated_unclosed_result_minor": 7546, "balanced": True}
        assert january["cash_movements"]["opening_minor"] == 44398
        assert january["cash_movements"]["activity_minor"] == 1500
        assert january["cash_movements"]["closing_minor"] == 45898
        assert january == reporting.report(map_id=mapping["id"], period_id="jan", as_of_date="2027-01-02", organization_code="ORG", entity_code="ENTITY", actor=actor)
