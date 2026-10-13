"""Actual original paired sources, observed periods and aggregate read ceilings."""

import json
import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.intercompany_group_diagnostic import IntercompanyDiagnosticSelection, IntercompanyReportPin
from reconforge.infrastructure.postgres_intercompany_group_diagnostic import (
    PostgresIntercompanyGroupDiagnosticRepository,
)
from tests.intercompany_fx_fixture import rate
from tests.test_postgres_intercompany_cashflow import opening
from tests.test_postgres_intercompany_fx import PERIODS, FxRuntime, backing_digest, cash, preparation, publish

pytest_plugins = ("tests.test_postgres_intercompany_fx",)


def closed_source(rt: FxRuntime, suffix: str) -> IntercompanyReportPin:
    with rt.actor("maker") as (_, repository, actor):
        original = repository.prepare(replace(preparation(), reference="DIAGNOSTIC-" + suffix),
                                      command_id="prepare-diagnostic-" + suffix, actor=actor)
    original = publish(rt, original, "diagnostic-" + suffix)
    basis = opening(rt, original)
    cash(rt, original["source_id"], suffix="diagnostic-cash-" + suffix)
    with rt.actor("maker") as (_, repository, actor):
        valued = repository.prepare_revaluation(original["source_id"],
            rates={"seller": rate("1.32", "2026-10-05"), "buyer": rate("0.82", "2026-10-05")},
            period_ids=PERIODS, posting_date="2026-10-05", reason="Reviewed original period valuation",
            command_id="diagnostic-revalue-" + suffix, actor=actor)
    publish(rt, valued, "diagnostic-revalue-" + suffix)
    with rt.actor("maker") as (_, repository, actor):
        final = repository.prepare_elimination(original["source_id"],
            closing_rates={"seller": rate("1.32", "2026-10-06"), "buyer": rate("0.82", "2026-10-06")},
            income_rates={book: {day: rate(value, day) for day, value in zip(
                ("2026-10-03", "2026-10-04", "2026-10-05"), values, strict=True)}
                for book, values in (("seller", ("1.25", "1.3", "1.32")), ("buyer", ("0.8", "0.78", "0.82")))},
            period_ids=PERIODS, posting_date="2026-10-06", reason="Reviewed original selected-source native elimination",
            command_id="diagnostic-eliminate-" + suffix, actor=actor)
    final = publish(rt, final, "diagnostic-eliminate-" + suffix)
    with rt.actor("poster") as (_, repository, actor):
        report = repository.report(original["source_id"], actor=actor)
    return IntercompanyReportPin(basis, final["id"], final["plan_digest"], report["report_digest"])


def selection(*pins: IntercompanyReportPin) -> IntercompanyDiagnosticSelection:
    return IntercompanyDiagnosticSelection(tuple(sorted(pins, key=lambda pin: pin.opening.source_id)))


def write_original(proof):
    if directory := os.environ.get("RECONFORGE_IC2_DIAGNOSTIC_PROOF_DIR"):
        path = Path(directory, "original-group-diagnostic-" + uuid4().hex + ".json")
        with path.open("x", encoding="utf8") as handle:
            json.dump(proof, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def test_two_actual_complete_sources_reconcile_translated_cash_and_native_adjustment_and_observed_period(runtime: FxRuntime):
    import psycopg

    pins = selection(closed_source(runtime, "first"), closed_source(runtime, "second"))
    with runtime.actor("poster") as (connection, _, actor):
        before = backing_digest(connection, runtime.base.tenant)
        proof = PostgresIntercompanyGroupDiagnosticRepository(connection, runtime.base.tenant).evidence(pins, actor=actor)
        report = proof["diagnostic"]
        cash_row = next(row for row in report["trial_balance_bridge"] if row["role"] == "cash")
        assert cash_row["translated_minor"] == cash_row["combined_minor"] == 202
        assert cash_row["native_adjustment_minor"] == 0
        assert report["cash_equation"] == {"opening_minor": 0, "operating_net_minor": 0, "fx_on_cash_minor": 202, "closing_minor": 202}
        assert report["income_statement"] == {"income_minor": 1126, "expense_minor": 342, "result_minor": 784}
        assert report["balance_sheet"]["equity_minor"] == -582
        assert len(report["source_members"]) == 2
        assert sum(len(capture["original_rows"]["effects"]) for capture in proof["source_captures"]) == 14
        assert report["native_period_observations"][0]["status"] == "Open"
        assert report["formal_close_workflow_assessed"] is report["whole_group_membership_proven"] is False
        assert proof["native_period_capture_scope"] == "one-readonly-statement-snapshot-without-period-row-locks"
        # While the report still retains both original source locks, a period
        # writer can acquire its exact row. This would fail with the former
        # added period SHARE and proves the diagnostic introduces no such lock.
        with psycopg.connect(runtime.base.admin_dsn) as observer:
            assert observer.execute("SELECT id FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id='period' FOR UPDATE NOWAIT",
                                    (runtime.base.tenant,)).fetchone()[0] == "period"
            observer.rollback()
        assert backing_digest(connection, runtime.base.tenant) == before
        write_original(proof)


@pytest.mark.parametrize("permission", ["finance_core.read", "intercompany_fx.read"])
def test_actual_aggregate_reporting_values_require_current_amount_admission_when_each_source_is_within_scope(runtime: FxRuntime,
                                                                                                           monkeypatch, permission):
    import reconforge.infrastructure.postgres_operational_finance as core

    pins = selection(closed_source(runtime, "cap-first"), closed_source(runtime, "cap-second"))
    observed = []
    def cap(principal, **context):
        if context["required_permission"] == permission and context.get("amount") is not None:
            observed.append(context["amount"])
            return evaluate_principal_access(principal, maximum_amount=Decimal("200"), **context)
        return evaluate_principal_access(principal, **context)
    monkeypatch.setattr(core, "evaluate_principal_access", cap)
    with runtime.actor("poster") as (connection, _, actor):
        repo = PostgresIntercompanyGroupDiagnosticRepository(connection, runtime.base.tenant)
        for pin in pins.pins:
            assert repo.cashflow.evidence(pin.opening.source_id, opening=pin.opening, actor=actor)["native_execution_proven"] is True
        before = backing_digest(connection, runtime.base.tenant)
        with pytest.raises(FinancePostingError) as refused:
            repo.evidence(pins, actor=actor)
        assert "denied" in refused.value.code and any(amount == Decimal("200.02") for amount in observed)
        assert backing_digest(connection, runtime.base.tenant) == before
