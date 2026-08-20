from __future__ import annotations

import json
from pathlib import Path

import pytest

from reconforge.application.individual_cashflow_control import (
    run_individual_cashflow_control_files,
    verify_individual_cashflow_report,
    write_individual_cashflow_report,
)
from reconforge.domain.individual_cashflow_control import (
    CashBudgetLine,
    CashTransaction,
    IndividualCashflowControlError,
    run_individual_cashflow_control,
)
from reconforge.utils.money import Money

TRANSACTIONS = Path("examples/individual_cashflow/transactions.json")
BUDGETS = Path("examples/individual_cashflow/budgets.json")


def _transaction(identifier: str, amount: str, category: str = "software") -> CashTransaction:
    return CashTransaction(identifier, "2026-07-01", "expense", category, Money.from_exact(amount, "USD"), identifier, f"src:{identifier}")


def test_individual_cashflow_exact_budget_statuses_and_lineage() -> None:
    run = run_individual_cashflow_control_files(TRANSACTIONS, BUDGETS, currency="USD")
    assert run.status_counts == {"no_activity": 1, "over_budget": 1, "within_budget": 2}
    decisions = {(item.period, item.flow_type, item.category): item for item in run.decisions}
    assert decisions[("2026-07", "expense", "software")].actual.amount == 100
    assert decisions[("2026-07", "expense", "travel")].status == "over_budget"
    assert decisions[("2026-08", "expense", "software")].status == "no_activity"
    assert decisions[("2026-07", "income", "client-work")].status == "within_budget"
    assert all(item.actual.currency == "USD" for item in run.decisions)


def test_individual_cashflow_is_permutation_invariant_and_replay_verifiable(tmp_path: Path) -> None:
    transactions = (_transaction("tx-b", "2"), _transaction("tx-a", "3"))
    budget = (CashBudgetLine("budget-1", "2026-07", "expense", "software", Money.from_exact("5", "USD"), "src:budget"),)
    first = run_individual_cashflow_control(transactions, budget, input_digests=("b" * 64, "a" * 64))
    second = run_individual_cashflow_control(tuple(reversed(transactions)), budget, input_digests=("a" * 64, "b" * 64))
    assert first.decision_digest == second.decision_digest
    report = tmp_path / "report.json"
    write_individual_cashflow_report(first, report)
    assert verify_individual_cashflow_report(report)["decision_digest"] == first.decision_digest
    tampered = json.loads(report.read_text(encoding="utf-8"))
    tampered["decisions"][0]["reason_code"] = "TAMPERED"
    report.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(IndividualCashflowControlError, match="digest"):
        verify_individual_cashflow_report(report)


def test_individual_cashflow_rejects_float_duplicate_and_currency_mismatch() -> None:
    with pytest.raises(IndividualCashflowControlError, match="transaction amount"):
        CashTransaction("tx-float", "2026-07-01", "expense", "software", 1.25, "r", "s")  # type: ignore[arg-type]
    with pytest.raises(IndividualCashflowControlError, match="unique"):
        run_individual_cashflow_control((_transaction("same", "1"), _transaction("same", "2")))
    with pytest.raises(IndividualCashflowControlError, match="one currency"):
        run_individual_cashflow_control(
            (_transaction("usd", "1"), CashTransaction("eur", "2026-07-01", "expense", "software", Money.from_exact("1", "EUR"), "eur", "src:eur"))
        )


def test_individual_cashflow_requires_activity_or_budget() -> None:
    with pytest.raises(IndividualCashflowControlError, match="at least one"):
        run_individual_cashflow_control(())
