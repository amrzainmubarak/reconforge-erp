"""Reporting values require current amount authority in their own currency."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import FinancePostingError
from tests.intercompany_fx_fixture import rate
from tests.test_postgres_intercompany_fx import (
    PERIODS,
    FxRuntime,
    export_cycle,
    intercompany_fx_database,
    publish,
    pytestmark,
    receipt_database,
    recognize,
    runtime,
)

__all__ = ["intercompany_fx_database", "pytestmark", "receipt_database", "runtime"]


@pytest.mark.parametrize("permission", ["finance_core.read", "intercompany_fx.read"])
@pytest.mark.parametrize("operation", ["source", "plan", "evidence", "report"])
def test_translated_cash_cannot_escape_current_reporting_amount_cap(
    runtime: FxRuntime, monkeypatch: pytest.MonkeyPatch, permission: str, operation: str,
) -> None:
    import reconforge.infrastructure.postgres_operational_finance as authority

    original = recognize(runtime)
    # Exact full settlement at the original functional rates leaves no AR/AP.
    with runtime.actor("maker") as (_, repository, actor):
        settled = repository.prepare_settlement(original["source_id"], transaction_minor=10001,
            rates={"seller": rate("1.25", "2026-10-04"), "buyer": rate("0.8", "2026-10-04")},
            period_ids=PERIODS, posting_date="2026-10-04", reason="Exact original full cash",
            command_id="whole-original-cash", actor=actor)
    settled = publish(runtime, settled, "whole-original-cash")
    day = "2026-10-05"
    with runtime.actor("maker") as (_, repository, actor):
        adjustment = repository.prepare_elimination(original["source_id"],
            closing_rates={"seller": rate("0.0125", day), "buyer": rate("0.008", day)},
            income_rates={"seller": {"2026-10-03": rate("1.25", "2026-10-03"), "2026-10-04": rate("1.25", "2026-10-04")},
                "buyer": {"2026-10-03": rate("0.8", "2026-10-03"), "2026-10-04": rate("0.8", "2026-10-04")}},
            period_ids=PERIODS, posting_date=day, reason="Actual native reporting observation",
            command_id="reporting-observation", actor=actor)
    adjustment = publish(runtime, adjustment, "reporting-observation")
    assert adjustment["equation"]["positions"]["adjustment"]["amount_minor"] == 10001
    assert [abs(next(row["balance_minor"] for row in adjustment["equation"]["translations"][book]["accounts"]
        if row["role"] == "cash")) for book in ("seller", "buyer")] == [1000080, 1000125]
    with runtime.actor("poster") as (connection, repository, actor):
        report = repository.report(original["source_id"], actor=actor)
        export_cycle(connection, repository, actor, [original, settled, adjustment], report)
        before = repository.evidence(adjustment["id"], actor=actor)
        def cap(principal: Any, **context: Any) -> Any:
            return evaluate_principal_access(principal,
                maximum_amount=Decimal("150") if context["required_permission"] == permission else None, **context)
        monkeypatch.setattr(authority, "evaluate_principal_access", cap)
        with pytest.raises(FinancePostingError, match="denied"):
            if operation == "source":
                repository.get_source(original["source_id"], actor=actor)
            elif operation == "plan":
                repository.get_plan(adjustment["id"], actor=actor)
            elif operation == "evidence":
                repository.evidence(adjustment["id"], actor=actor)
            else:
                repository.report(original["source_id"], actor=actor)
        monkeypatch.undo()
        assert repository.evidence(adjustment["id"], actor=actor) == before
        def sufficient_cap(principal: Any, **context: Any) -> Any:
            return evaluate_principal_access(principal, maximum_amount=Decimal("20000"), **context)
        monkeypatch.setattr(authority, "evaluate_principal_access", sufficient_cap)
        assert repository.evidence(adjustment["id"], actor=actor) == before
        # A source-only adjustment scope has no original amount; the existing
        # policy refuses a maximum there. Restore the original policy before
        # checking whole-report byte equality rather than relaxing that rule.
        monkeypatch.undo()
        assert repository.report(original["source_id"], actor=actor) == report
