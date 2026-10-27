"""Tests for intercompany elimination API schemas and SQLite repository."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from reconforge.api.routes.intercompany_elimination import (
    IntercompanyLineInput,
    ProfitInStockRequest,
)
from reconforge.domain.intercompany_elimination import (
    IntercompanyEliminationInputLine,
    IntercompanyProfitInStockRule,
    calculate_profit_in_stock_elimination,
    prepare_intercompany_eliminations,
)
from reconforge.infrastructure.sqlite_intercompany_elimination import (
    SQLiteIntercompanyEliminationRepository,
)
from reconforge.utils.money import Money


def test_intercompany_schema_validation() -> None:
    digest = "a" * 64
    valid_line = {
        "transaction_id": "TX-01",
        "period_name": "2026-Q1",
        "entity_code": "ENTITY_A",
        "counterparty_code": "ENTITY_B",
        "reference": "REF-100",
        "group_account_code": "ACC-IC-1",
        "account_type": "Asset",
        "amount": {
            "amount": "1000.00",
            "currency": "USD",
            "minor_units": 2,
            "rounding_policy": "ROUND_HALF_UP",
        },
        "source_reference": "ref:source:01",
        "source_digest": digest,
    }
    line = IntercompanyLineInput.model_validate(valid_line)
    domain_line = line.to_domain()
    assert domain_line.entity_code == "ENTITY_A"
    assert domain_line.amount.amount == 1000

    # Malformed digest rejected
    with pytest.raises(ValidationError):
        IntercompanyLineInput.model_validate({**valid_line, "source_digest": "not-a-sha256"})

    # Invalid account type rejected
    with pytest.raises(ValidationError):
        IntercompanyLineInput.model_validate({**valid_line, "account_type": "InvalidType"})


def test_profit_in_stock_schema_validation() -> None:
    valid = {
        "rule_id": "RULE-01",
        "selling_entity": "SUB_A",
        "buying_entity": "PARENT",
        "inventory_item_code": "ITEM-101",
        "margin_basis_points": 2000,
        "ending_inventory_cost_minor": 50000,
        "nci_share_basis_points": 1000,
        "currency": "USD",
        "debit_account": "COGS_ELIMINATION",
        "credit_account": "INVENTORY_VALUATION",
    }
    req = ProfitInStockRequest.model_validate(valid)
    assert req.margin_basis_points == 2000

    # Margin bps out of bounds rejected
    with pytest.raises(ValidationError):
        ProfitInStockRequest.model_validate({**valid, "margin_basis_points": 15000})


def test_sqlite_intercompany_elimination_lifecycle() -> None:
    conn = sqlite3.connect(":memory:")
    repo = SQLiteIntercompanyEliminationRepository(conn)

    # 1. Test Profit in Stock Persistence
    rule = IntercompanyProfitInStockRule(
        rule_id="RULE-SQLITE-01",
        selling_entity="ENTITY_SUB",
        buying_entity="ENTITY_PARENT",
        inventory_item_code="PROD-A",
        margin_basis_points=2500,
        ending_inventory_cost_minor=200_000,
        nci_share_basis_points=2000,
        currency="USD",
    )
    elimination = calculate_profit_in_stock_elimination(rule)
    elim_id = repo.save_profit_in_stock_elimination("default", rule, elimination, actor_label="test-actor")
    assert elim_id == elimination.elimination_id

    records = repo.list_profit_in_stock_eliminations("default")
    assert len(records) == 1
    assert records[0]["unrealized_profit_minor"] == 50_000
    assert records[0]["parent_share_minor"] == 40_000
    assert records[0]["nci_share_minor"] == 10_000

    # 2. Test Elimination Run Persistence
    digest_a = "c" * 64
    digest_b = "d" * 64
    line1 = IntercompanyEliminationInputLine(
        transaction_id="TX-101",
        period_name="2026-Q1",
        entity_code="ENT_1",
        counterparty_code="ENT_2",
        reference="PAIR-01",
        group_account_code="ACC_REC",
        account_type="Asset",
        amount=Money.from_exact("100.00", "USD"),
        source_reference="src:1",
        source_digest=digest_a,
    )
    line2 = IntercompanyEliminationInputLine(
        transaction_id="TX-102",
        period_name="2026-Q1",
        entity_code="ENT_2",
        counterparty_code="ENT_1",
        reference="PAIR-01",
        group_account_code="ACC_PAY",
        account_type="Liability",
        amount=Money.from_exact("-100.00", "USD"),
        source_reference="src:2",
        source_digest=digest_b,
    )
    result = prepare_intercompany_eliminations(
        (line1, line2),
        reporting_currency="USD",
        prepared_by="test-user",
        prepared_at="2026-10-19T10:00:00Z",
    )
    run_id = repo.save_elimination_result("default", result, actor_label="test-user")
    assert run_id.startswith("ICERUN")

    runs = repo.list_elimination_runs("default")
    assert len(runs) == 1
    assert runs[0]["reporting_currency"] == "USD"

    run_detail = repo.get_elimination_run("default", run_id)
    assert run_detail is not None
    assert run_detail["result_digest"] == result.result_digest
    assert len(run_detail["result_payload"]["resolutions"]) == 1
