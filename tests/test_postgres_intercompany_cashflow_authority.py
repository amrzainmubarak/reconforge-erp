"""Reporting-value amount context, distinct from original functional GL amounts."""

from decimal import Decimal

import pytest

from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres_intercompany_cashflow import PostgresIntercompanyCashflowRepository
from tests.intercompany_fx_fixture import rate
from tests.test_postgres_intercompany_cashflow import opening, write_original
from tests.test_postgres_intercompany_fx import PERIODS, FxRuntime, cash, publish, recognize

pytest_plugins = ("tests.test_postgres_intercompany_fx",)


def fully_settled(rt: FxRuntime):
    original = recognize(rt)
    cash(rt, original["source_id"])
    cash(rt, original["source_id"], transaction_minor=7001, day="2026-10-05", suffix="remaining")
    day = "2026-10-06"
    with rt.actor("maker") as (_, repository, actor):
        final = repository.prepare_elimination(original["source_id"], closing_rates={"seller": rate("0.5", day), "buyer": rate("0.2", day)},
            income_rates={"seller": {"2026-10-03": rate("1.25", "2026-10-03"), "2026-10-04": rate("1.3", "2026-10-04"), "2026-10-05": rate("1.3", "2026-10-05")},
                "buyer": {"2026-10-03": rate("0.8", "2026-10-03"), "2026-10-04": rate("0.78", "2026-10-04"), "2026-10-05": rate("0.78", "2026-10-05")}},
            period_ids=PERIODS, posting_date=day, reason="Reviewed fully settled original source with captured presentation rates",
            command_id="prepare-reporting-amount", actor=actor)
    publish(rt, final, "reporting-amount")
    return original


@pytest.mark.parametrize("permission", ["finance_core.read", "intercompany_fx.read"])
@pytest.mark.parametrize("group_only", [False, True])
def test_actual_full_cash_reporting_value_uses_current_read_ceiling_as_well_as_native_amount(runtime: FxRuntime, monkeypatch,
        permission: str, group_only: bool):
    import reconforge.infrastructure.postgres_operational_finance as core

    original = fully_settled(runtime)
    basis = opening(runtime, original)
    with runtime.actor("poster") as (connection, _, actor):
        baseline = PostgresIntercompanyCashflowRepository(connection, runtime.base.tenant).evidence(
            original["source_id"], opening=basis, actor=actor)
    assert baseline["cashflow"]["books"]["seller"]["native_cash_minor"] == 13001
    assert baseline["cashflow"]["books"]["buyer"]["native_cash_minor"] == -7801
    assert baseline["cashflow"]["books"]["seller"]["closing_minor"] == 26002
    assert baseline["cashflow"]["books"]["buyer"]["closing_minor"] == -39005
    write_original(baseline)
    observed = []
    def cap(principal, **context):
        if context["required_permission"] == permission and context.get("amount") is not None and (not group_only or context["entity_id"] == "group"):
            observed.append(context["amount"])
            return evaluate_principal_access(principal, maximum_amount=Decimal("150"), **context)
        return evaluate_principal_access(principal, **context)
    monkeypatch.setattr(core, "evaluate_principal_access", cap)
    with runtime.actor("poster") as (connection, _, actor), pytest.raises(FinancePostingError) as refused:
        PostgresIntercompanyCashflowRepository(connection, runtime.base.tenant).evidence(
            original["source_id"], opening=basis, actor=actor)
    assert "denied" in refused.value.code
    assert any(amount > Decimal("150") for amount in observed)
