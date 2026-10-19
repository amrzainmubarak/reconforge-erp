"""Tests for consolidated financial statements API schemas, SQLite repository, and calculations."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from reconforge.api.routes.consolidated_financial_statements import (
    EntityTrialBalanceInput,
)
from reconforge.domain.consolidated_financial_statements import (
    EntityTrialBalance,
    GroupIntercompanyEliminations,
    generate_consolidated_statements,
)
from reconforge.infrastructure.sqlite_consolidated_statements import (
    SQLiteConsolidatedStatementsRepository,
)


def _sample_entities() -> tuple[EntityTrialBalance, EntityTrialBalance]:
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
    sub = EntityTrialBalance(
        entity_id="ENT_SUB_EU",
        functional_currency="EUR",
        fx_rate_to_group_scaled=1_100_000,
        parent_ownership_bips=8_000,
        cash_minor=100_000,
        trade_receivables_minor=80_000,
        intercompany_receivables_minor=0,
        inventory_minor=60_000,
        ppe_minor=150_000,
        other_assets_minor=0,
        trade_payables_minor=50_000,
        intercompany_payables_minor=45_455,
        short_term_debt_minor=20_000,
        long_term_debt_minor=100_000,
        other_liabilities_minor=0,
        share_capital_minor=150_000,
        retained_earnings_opening_minor=20_000,
        gross_revenue_minor=300_000,
        intercompany_revenue_minor=0,
        cogs_minor=180_000,
        intercompany_cogs_minor=36_364,
        operating_expenses_minor=50_000,
        depreciation_minor=10_000,
        finance_costs_minor=5_000,
        tax_expense_minor=10_000,
    )
    return parent, sub


def test_consolidated_statements_schema_validation() -> None:
    valid_entity = {
        "entity_id": "ENT_01",
        "functional_currency": "USD",
        "fx_rate_to_group_scaled": 1_000_000,
        "parent_ownership_bips": 10_000,
        "cash_minor": 100_000,
        "trade_receivables_minor": 50_000,
        "intercompany_receivables_minor": 0,
        "inventory_minor": 40_000,
        "ppe_minor": 200_000,
        "other_assets_minor": 0,
        "trade_payables_minor": 30_000,
        "intercompany_payables_minor": 0,
        "short_term_debt_minor": 20_000,
        "long_term_debt_minor": 100_000,
        "other_liabilities_minor": 0,
        "share_capital_minor": 200_000,
        "retained_earnings_opening_minor": 10_000,
        "gross_revenue_minor": 250_000,
        "intercompany_revenue_minor": 0,
        "cogs_minor": 150_000,
        "intercompany_cogs_minor": 0,
        "operating_expenses_minor": 40_000,
        "depreciation_minor": 10_000,
        "finance_costs_minor": 5_000,
        "tax_expense_minor": 10_000,
    }
    entity_input = EntityTrialBalanceInput.model_validate(valid_entity)
    domain_entity = entity_input.to_domain()
    assert domain_entity.entity_id == "ENT_01"
    assert domain_entity.cash_minor == 100_000

    # Negative cash rejected
    with pytest.raises(ValidationError):
        EntityTrialBalanceInput.model_validate({**valid_entity, "cash_minor": -1})

    # Float amount rejected
    with pytest.raises(ValidationError):
        EntityTrialBalanceInput.model_validate({**valid_entity, "cash_minor": 100.50})

    # Ownership bips out of range rejected
    with pytest.raises(ValidationError):
        EntityTrialBalanceInput.model_validate({**valid_entity, "parent_ownership_bips": 10_500})


def test_sqlite_consolidated_statements_repository() -> None:
    conn = sqlite3.connect(":memory:")
    repo = SQLiteConsolidatedStatementsRepository(conn)

    parent, sub = _sample_entities()
    eliminations = GroupIntercompanyEliminations(
        intercompany_receivables_eliminated_minor=50_000,
        intercompany_payables_eliminated_minor=50_000,
        intercompany_revenue_eliminated_minor=40_000,
        intercompany_cogs_eliminated_minor=40_000,
        profit_in_stock_eliminated_minor=5_000,
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

    run_id = repo.save_run(
        workspace_id="ws-test",
        statements=statements,
        prepared_by="auditor1",
    )
    assert run_id.startswith("csr_GRP_GLOBAL_FY2026_Q1_")

    record = repo.get_run(workspace_id="ws-test", run_id=run_id)
    assert record is not None
    assert record["group_id"] == "GRP_GLOBAL"
    assert record["reporting_currency"] == "USD"
    assert record["statements"]["balance_sheet"]["balanced"] is True
    assert record["statements"]["cash_flow_statement"]["reconciled_with_balance_sheet"] is True

    # List runs
    runs = repo.list_runs(workspace_id="ws-test", group_id="GRP_GLOBAL")
    assert len(runs) == 1
    assert runs[0]["id"] == run_id
