"""Domain and invariant tests for intercompany elimination and profit-in-stock rules."""

from __future__ import annotations

import pytest

from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.intercompany_elimination import (
    IntercompanyEliminationInputLine,
    IntercompanyProfitInStockRule,
    calculate_profit_in_stock_elimination,
    diagnose_intercompany_discrepancies,
    prepare_intercompany_eliminations,
)
from reconforge.utils.money import Money


def test_profit_in_stock_elimination_conservation():
    """Verify exact integer conservation of unrealized profit between parent and NCI."""
    rule = IntercompanyProfitInStockRule(
        rule_id="RULE-PIS-001",
        selling_entity="SUB_A",
        buying_entity="PARENT_CORP",
        inventory_item_code="PROD-WIDGET-01",
        margin_basis_points=2500,  # 25.00%
        ending_inventory_cost_minor=100_000,  # 1,000.00 USD
        nci_share_basis_points=2000,  # 20.00% minority interest in SUB_A
        currency="USD",
    )
    elimination = calculate_profit_in_stock_elimination(rule)

    # 100,000 * 2500 / 10000 = 25,000
    assert elimination.unrealized_profit_minor == 25_000
    # NCI: 25,000 * 2000 / 10000 = 5,000
    assert elimination.nci_share_minor == 5_000
    # Parent: 25,000 - 5,000 = 20,000
    assert elimination.parent_share_minor == 20_000
    assert elimination.parent_share_minor + elimination.nci_share_minor == elimination.unrealized_profit_minor
    assert elimination.currency == "USD"
    assert elimination.debit_account == "COGS_ELIMINATION"
    assert elimination.credit_account == "INVENTORY_VALUATION"


def test_profit_in_stock_rounding_half_up_preservation():
    """Test odd amount rounding preserves exact sum without penny leakage."""
    rule = IntercompanyProfitInStockRule(
        rule_id="RULE-PIS-ROUND",
        selling_entity="SUB_B",
        buying_entity="PARENT_CORP",
        inventory_item_code="PROD-ODD-01",
        margin_basis_points=3333,  # 33.33%
        ending_inventory_cost_minor=10_003,
        nci_share_basis_points=1500,  # 15.00%
        currency="USD",
    )
    elimination = calculate_profit_in_stock_elimination(rule)
    # Check that parent + NCI strictly equals unrealized profit
    assert elimination.parent_share_minor + elimination.nci_share_minor == elimination.unrealized_profit_minor
    assert elimination.unrealized_profit_minor > 0


def test_profit_in_stock_validation_refusals():
    """Verify fail-closed domain validations for invalid entities or basis points."""
    with pytest.raises(ConsolidationError, match="selling and buying entities must differ"):
        IntercompanyProfitInStockRule(
            rule_id="RULE-FAIL",
            selling_entity="SAME_ENTITY",
            buying_entity="SAME_ENTITY",
            inventory_item_code="PROD-01",
            margin_basis_points=2000,
            ending_inventory_cost_minor=5000,
            nci_share_basis_points=0,
            currency="USD",
        )

    with pytest.raises(ConsolidationError, match="Margin basis points must be between"):
        IntercompanyProfitInStockRule(
            rule_id="RULE-FAIL-MARGIN",
            selling_entity="SUB_A",
            buying_entity="PARENT",
            inventory_item_code="PROD-01",
            margin_basis_points=12_000,  # Invalid: > 10,000
            ending_inventory_cost_minor=5000,
            nci_share_basis_points=0,
            currency="USD",
        )


def test_intercompany_elimination_reciprocal_pairing_and_diagnostics():
    """Verify reciprocal pairing proposal generation and discrepancy diagnosis."""
    digest_a = "a" * 64
    digest_b = "b" * 64

    # Reciprocal balanced pair
    line1 = IntercompanyEliminationInputLine(
        transaction_id="TX-001",
        period_name="2026-Q1",
        entity_code="CORP_US",
        counterparty_code="CORP_UK",
        reference="INV-IC-101",
        group_account_code="IC_RECEIVABLE",
        account_type="Asset",
        amount=Money.from_exact("5000.00", "USD"),
        source_reference="ledger:us:101",
        source_digest=digest_a,
    )
    line2 = IntercompanyEliminationInputLine(
        transaction_id="TX-002",
        period_name="2026-Q1",
        entity_code="CORP_UK",
        counterparty_code="CORP_US",
        reference="INV-IC-101",
        group_account_code="IC_PAYABLE",
        account_type="Liability",
        amount=Money.from_exact("-5000.00", "USD"),
        source_reference="ledger:uk:202",
        source_digest=digest_b,
    )

    # Imbalanced pair
    line3 = IntercompanyEliminationInputLine(
        transaction_id="TX-003",
        period_name="2026-Q1",
        entity_code="CORP_US",
        counterparty_code="CORP_DE",
        reference="INV-IC-999",
        group_account_code="IC_RECEIVABLE",
        account_type="Asset",
        amount=Money.from_exact("2000.00", "USD"),
        source_reference="ledger:us:999",
        source_digest=digest_a,
    )
    line4 = IntercompanyEliminationInputLine(
        transaction_id="TX-004",
        period_name="2026-Q1",
        entity_code="CORP_DE",
        counterparty_code="CORP_US",
        reference="INV-IC-999",
        group_account_code="IC_PAYABLE",
        account_type="Liability",
        amount=Money.from_exact("-1800.00", "USD"),  # 200 USD discrepancy!
        source_reference="ledger:de:999",
        source_digest=digest_b,
    )

    lines = (line1, line2, line3, line4)
    result = prepare_intercompany_eliminations(
        lines,
        reporting_currency="USD",
        prepared_by="auditor_lead",
        prepared_at="2026-10-19T10:00:00Z",
    )

    assert len(result.resolutions) == 2
    proposed = [r for r in result.resolutions if r.status == "proposed"]
    unresolved = [r for r in result.resolutions if r.status == "unresolved"]

    assert len(proposed) == 1
    assert proposed[0].proposal is not None
    assert len(proposed[0].proposal.lines) == 2

    assert len(unresolved) == 1
    assert unresolved[0].reason == "source_group_is_not_zero_sum"

    diagnostics = diagnose_intercompany_discrepancies(lines, result)
    assert len(diagnostics) == 1
    assert diagnostics[0].discrepancy_minor == 20_000  # 200.00 USD
    assert diagnostics[0].reference == "INV-IC-999"
