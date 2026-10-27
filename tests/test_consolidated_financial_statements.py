"""Tests for multi-entity consolidated financial statements, classified balance sheet, and indirect cash flow."""

import pytest

from reconforge.domain.consolidated_financial_statements import (
    EntityTrialBalance,
    GroupIntercompanyEliminations,
    convert_fx,
    generate_consolidated_statements,
)
from reconforge.domain.finance_posting import FinancePostingError


def test_convert_fx_exact_and_rounding() -> None:
    # 1 EUR = 1.085000 USD (scale 1_000_000)
    rate = 1_085_000
    assert convert_fx(100_000, rate) == 108_500
    assert convert_fx(1, rate) == 1  # 1 * 1.085 = 1.085 -> 1
    assert convert_fx(0, rate) == 0


def test_consolidated_statements_two_entities_with_eliminations() -> None:
    # Parent (USD, 100% owned by shareholders)
    parent = EntityTrialBalance(
        entity_id="ENT_PARENT",
        functional_currency="USD",
        fx_rate_to_group_scaled=1_000_000,
        parent_ownership_bips=10_000,
        cash_minor=200_000,
        trade_receivables_minor=150_000,
        intercompany_receivables_minor=50_000,
        inventory_minor=120_000,
        ppe_minor=300_000,
        other_assets_minor=0,
        trade_payables_minor=100_000,
        intercompany_payables_minor=0,
        short_term_debt_minor=50_000,
        long_term_debt_minor=200_000,
        other_liabilities_minor=0,
        share_capital_minor=350_000,
        retained_earnings_opening_minor=50_000,
        gross_revenue_minor=500_000,
        intercompany_revenue_minor=40_000,
        cogs_minor=300_000,
        intercompany_cogs_minor=0,
        operating_expenses_minor=80_000,
        depreciation_minor=20_000,
        finance_costs_minor=10_000,
        tax_expense_minor=20_000,
    )

    # Subsidiary (EUR, functional currency EUR, group currency USD, fx rate 1.100000)
    # 80% owned by Parent, 20% Non-Controlling Interest (NCI)
    sub = EntityTrialBalance(
        entity_id="ENT_SUB_EU",
        functional_currency="EUR",
        fx_rate_to_group_scaled=1_100_000,  # 1 EUR = 1.10 USD
        parent_ownership_bips=8_000,  # 80%
        cash_minor=100_000,  # converted: 110_000
        trade_receivables_minor=80_000,  # converted: 88_000
        intercompany_receivables_minor=0,
        inventory_minor=60_000,  # converted: 66_000
        ppe_minor=150_000,  # converted: 165_000
        other_assets_minor=0,
        trade_payables_minor=50_000,  # converted: 55_000
        intercompany_payables_minor=45_455,  # converted ~ 50_000
        short_term_debt_minor=20_000,  # converted: 22_000
        long_term_debt_minor=100_000,  # converted: 110_000
        other_liabilities_minor=0,
        share_capital_minor=150_000,  # converted: 165_000
        retained_earnings_opening_minor=20_000,  # converted: 22_000
        gross_revenue_minor=300_000,  # converted: 330_000
        intercompany_revenue_minor=0,
        cogs_minor=180_000,  # converted: 198_000
        intercompany_cogs_minor=36_364,  # converted ~ 40_000
        operating_expenses_minor=50_000,  # converted: 55_000
        depreciation_minor=10_000,  # converted: 11_000
        finance_costs_minor=5_000,  # converted: 5_500
        tax_expense_minor=10_000,  # converted: 11_000
    )

    eliminations = GroupIntercompanyEliminations(
        intercompany_receivables_eliminated_minor=50_000,
        intercompany_payables_eliminated_minor=50_000,
        intercompany_revenue_eliminated_minor=40_000,
        intercompany_cogs_eliminated_minor=40_000,
        profit_in_stock_eliminated_minor=5_000,  # 5,000 unrealized profit eliminated from inventory and added to COGS
    )

    statements = generate_consolidated_statements(
        group_id="GRP_GLOBAL",
        organization_id="ORG_ALPHA",
        reporting_currency="USD",
        period_id="FY2026_Q1",
        period_start="2026-01-01",
        period_end="2026-03-31",
        as_of_date="2026-03-31",
        entities=[parent, sub],
        eliminations=eliminations,
    )

    assert statements.group_id == "GRP_GLOBAL"
    assert statements.reporting_currency == "USD"
    assert statements.balance_sheet["balanced"] is True

    # 1. Balance sheet equality: Assets == Liabilities + Equity
    bs = statements.balance_sheet
    assert bs["total_assets_minor"] == bs["total_liabilities_and_equity_minor"]
    assert bs["total_liabilities_minor"] + bs["equity"]["total_equity_minor"] == bs["total_assets_minor"]

    # 2. Net Intercompany receivables and payables are 0 after elimination
    assert bs["current_assets"]["intercompany_receivables_net_minor"] == 0

    # 3. P&L Net Profit attribution conservation: Parent + NCI == Consolidated Net Profit
    is_stmt = statements.income_statement
    assert is_stmt["attribution"]["conservation_verified"] is True
    assert (
        is_stmt["attribution"]["attributable_to_parent_minor"]
        + is_stmt["attribution"]["attributable_to_nci_minor"]
        == is_stmt["consolidated_net_profit_minor"]
    )

    # 4. Indirect Cash Flow ties out to closing cash
    cf = statements.cash_flow_statement
    assert cf["reconciled_with_balance_sheet"] is True
    assert cf["net_change_in_cash_minor"] == bs["current_assets"]["cash_minor"]
    assert cf["closing_cash_minor"] == bs["current_assets"]["cash_minor"]


def test_elimination_imbalance_raises_error() -> None:
    bad_elim = GroupIntercompanyEliminations(
        intercompany_receivables_eliminated_minor=50_000,
        intercompany_payables_eliminated_minor=40_000,  # Mismatch!
        intercompany_revenue_eliminated_minor=20_000,
        intercompany_cogs_eliminated_minor=20_000,
        profit_in_stock_eliminated_minor=0,
    )
    with pytest.raises(FinancePostingError) as exc_info:
        bad_elim.validate()
    assert "must match intercompany payables elimination" in str(exc_info.value)
