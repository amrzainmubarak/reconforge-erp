"""Restricted native closing valuation, explicit inverse, current grants and SQL closure."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.operational_fx_tax import HistoricalRate
from reconforge.infrastructure.postgres_operational_fx_revaluation_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.infrastructure.postgres_operational_fx_tax import PostgresOperationalFxTaxRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_operational_fx_tax import (
    finish_fx,
    fx_runtime,
    native_balances,
    prepare_fx,
    pytestmark,
    receipt_database,
    settle_fx,
)

__all__ = ["fx_runtime", "pytestmark", "receipt_database"]


def revalue_fx(runtime: ReceiptRuntime, source: str, rate: str = "1.35", command: str = "closing") -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        repository = PostgresOperationalFxTaxRepository(connection, runtime.tenant)
        args = {"closing_rate": HistoricalRate(rate, "Retained synthetic closing rate", "2026-10-03T23:00:00Z"),
                "unrealized_gain_account_code": "UGAIN", "unrealized_loss_account_code": "ULOSS", "period_id": "period",
                "posting_date": "2026-10-03", "reason": "Exact outstanding monetary closing valuation", "command_id": command, "actor": actor}
        plan = repository.prepare_revaluation(source, **args)
        assert repository.prepare_revaluation(source, **args) == plan
        return plan


def reverse_fx(runtime: ReceiptRuntime, source: str, original: str) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        repository = PostgresOperationalFxTaxRepository(connection, runtime.tenant)
        args = {"original_revaluation_id": original, "period_id": "period", "posting_date": "2026-10-04",
                "reason": "Exact reviewed original closing valuation inverse", "command_id": "reverse-closing", "actor": actor}
        plan = repository.prepare_revaluation_reversal(source, **args)
        assert repository.prepare_revaluation_reversal(source, **args) == plan
        return plan


@pytest.mark.parametrize(("rate", "difference", "role"), [("1.35", 740, "UGAIN"), ("1.15", -740, "ULOSS")])
def test_partial_native_ar_closing_gain_loss_and_explicit_inverse_before_final_settlement(
    fx_runtime: ReceiptRuntime, rate: str, difference: int, role: str,
) -> None:
    runtime = fx_runtime
    initial = finish_fx(runtime, prepare_fx(runtime))
    finish_fx(runtime, settle_fx(runtime, initial["source_id"], 4000, "1.3", "2026-10-02"))
    valuation = finish_fx(runtime, revalue_fx(runtime, initial["source_id"], rate))
    assert valuation["equation"]["unrealized_fx_minor"] == difference and valuation["receipt_id"] is None
    balances = native_balances(runtime)
    assert balances["AR"] == 9251 + difference and balances[role] == -difference
    with runtime.actor("poster") as (connection, _, actor):
        repository = PostgresOperationalFxTaxRepository(connection, runtime.tenant)
        detail = repository.get(initial["source_id"], actor=actor)
        assert detail["foreign_outstanding_minor"] == 7401 and detail["functional_outstanding_minor"] == 9251
        assert detail["valued_functional_outstanding_minor"] == 9251 + difference and detail["active_revaluation_plan_id"] == valuation["id"]
        assert len(repository.plan_evidence(valuation["id"], actor=actor)["phases"]) == 4
    with pytest.raises(FinancePostingError, match="reverse"):
        settle_fx(runtime, initial["source_id"], 7401, "1.2", "2026-10-05")
    inverse = finish_fx(runtime, reverse_fx(runtime, initial["source_id"], valuation["id"]))
    assert inverse["snapshot"]["entry"]["reverses_posting_id"] == valuation["posting_effect_id"]
    assert inverse["equation"]["unrealized_fx_minor"] == -difference
    assert native_balances(runtime)["AR"] == 9251 and native_balances(runtime)[role] == 0
    finish_fx(runtime, settle_fx(runtime, initial["source_id"], 7401, "1.2", "2026-10-05"))
    assert native_balances(runtime)["AR"] == 0
    with runtime.actor("poster") as (connection, _, actor):
        detail = PostgresOperationalFxTaxRepository(connection, runtime.tenant).get(initial["source_id"], actor=actor)
        assert detail["foreign_outstanding_minor"] == detail["valued_functional_outstanding_minor"] == 0
        assert detail["active_revaluation_plan_id"] is None and len(detail["plans"]) == 5
        assert connection.execute("SELECT count(*) n FROM reconforge.ar_receipts WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 2
        effect = connection.execute("SELECT reverses_effect_id FROM reconforge.finance_posting_effects WHERE tenant_id=%s AND id=%s", (runtime.tenant, inverse["posting_effect_id"])).fetchone()
        assert effect["reverses_effect_id"] == valuation["posting_effect_id"]


def test_closing_valuation_sql_phase_bypass_late_failure_and_current_inverse_permission(
    fx_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    runtime = fx_runtime
    initial = finish_fx(runtime, prepare_fx(runtime))
    plan = revalue_fx(runtime, initial["source_id"])
    with runtime.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError, match="independent"):
        PostgresOperationalFxTaxRepository(connection, runtime.tenant).review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Self", command_id="self", actor=actor)
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("poster") as (connection, _, _):
        connection.execute("UPDATE reconforge.operational_fx_plans SET phase=1 WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["id"]))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with runtime.actor("checker") as (connection, _, actor):
        PostgresOperationalFxTaxRepository(connection, runtime.tenant).review(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Review", command_id="review", actor=actor)
    with runtime.actor("poster") as (connection, _, actor):
        repository = PostgresOperationalFxTaxRepository(connection, runtime.tenant)
        remember = repository._remember

        def late(*args: Any, **kwargs: Any) -> dict[str, Any]:
            remember(*args, **kwargs)
            raise RuntimeError("Synthetic final valuation acknowledgement failure")

        with monkeypatch.context() as patch:
            patch.setattr(repository, "_remember", late)
            with pytest.raises(RuntimeError, match="Synthetic"):
                repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Post", command_id="post", actor=actor)
        assert repository.get(initial["source_id"], actor=actor)["active_revaluation_plan_id"] is None
        posted = repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], reason="Post", command_id="post", actor=actor)
    inverse = reverse_fx(runtime, initial["source_id"], posted["id"])
    with runtime.actor("maker") as (connection, _, _):
        connection.execute("UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by='maker',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='finance_core.reverse'", (runtime.tenant,))
    with runtime.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError, match="permission|authorization"):
        PostgresOperationalFxTaxRepository(connection, runtime.tenant).prepare_revaluation_reversal(initial["source_id"],
            original_revaluation_id=posted["id"], period_id="period", posting_date="2026-10-04", reason="Exact reviewed original closing valuation inverse",
            command_id="reverse-closing", actor=actor)
    with runtime.actor("maker") as (connection, _, _):
        connection.execute("UPDATE reconforge.identity_role_permissions SET active=TRUE,lifecycle_version=lifecycle_version+1,revoked_at=NULL,revoked_by=NULL,revocation_reason_code=NULL WHERE tenant_id=%s AND permission_name='finance_core.reverse'", (runtime.tenant,))
    finish_fx(runtime, inverse)


def test_concurrent_valuation_prepare_and_populated_revaluation_rollback_refusal(fx_runtime: ReceiptRuntime) -> None:
    import psycopg

    runtime = fx_runtime
    initial = finish_fx(runtime, prepare_fx(runtime))
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _: revalue_fx(runtime, initial["source_id"]), range(2)))
    assert first == second
    finish_fx(runtime, first)
    with psycopg.connect(runtime.admin_dsn) as admin, pytest.raises(psycopg.errors.RaiseException, match="refuses to discard"), admin.transaction():
        admin.execute(DOWNGRADE_SQL)
    with runtime.actor("poster") as (connection, _, actor):
        assert PostgresOperationalFxTaxRepository(connection, runtime.tenant).get(initial["source_id"], actor=actor)["active_revaluation_plan_id"] == first["id"]


def test_empty_revaluation_rollback_preserves_original_posted_source_and_reupgrade(fx_runtime: ReceiptRuntime) -> None:
    import psycopg

    runtime = fx_runtime
    original = finish_fx(runtime, prepare_fx(runtime))
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute(DOWNGRADE_SQL)
    with runtime.actor("poster") as (connection, _, actor):
        assert PostgresOperationalFxTaxRepository(connection, runtime.tenant).plan_evidence(original["id"], actor=actor)["native_effect"]["id"] == original["posting_effect_id"]
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute(UPGRADE_SQL)
    finish_fx(runtime, revalue_fx(runtime, original["source_id"]))


def test_actual_http_closing_valuation_and_generated_inverse_have_native_three_human_effects(
    fx_runtime: ReceiptRuntime, receipt_database: tuple[str, str], tmp_path: Path,
) -> None:
    from tests.test_postgres_operational_finance_api import client_for
    from tests.test_postgres_operational_fx_tax_api import install_owned_router

    runtime = fx_runtime
    initial = finish_fx(runtime, prepare_fx(runtime))
    request = {"command_id": "http-closing", "closing_rate": {"rate": "1.35", "source": "HTTP retained closing", "effective_at": "2026-10-03T23:00:00Z"},
               "unrealized_gain_account_code": "UGAIN", "unrealized_loss_account_code": "ULOSS", "period_id": "period",
               "posting_date": "2026-10-03", "reason": "HTTP governed outstanding closing valuation"}
    with client_for(runtime, receipt_database, tmp_path, "maker") as (client, headers):
        install_owned_router(client)
        path = f"/api/v1/operational-fx-tax/invoices/{initial['source_id']}/revaluations"
        invalid = client.post(path, headers=headers, json={**request, "closing_rate": {**request["closing_rate"], "rate": 1.35}})
        assert invalid.status_code == 422
        response = client.post(path, headers=headers, json=request)
        assert response.status_code == 200, response.text
        plan = response.json()["plan"]
        assert plan["equation"]["unrealized_fx_minor"] == "1140"
        assert client.post(path, headers=headers, json=request).json()["plan"] == plan
    for name, operation in (("checker", "review"), ("poster", "post")):
        with client_for(runtime, receipt_database, tmp_path, name) as (client, headers):
            install_owned_router(client)
            response = client.post(f"/api/v1/operational-fx-tax/plans/{plan['id']}/{operation}", headers=headers,
                json={"command_id": "http-closing-" + operation, "expected_plan_digest": plan["plan_digest"], "reason": "Independent closing " + operation})
            assert response.status_code == 200, response.text
            plan = response.json()["plan"]
    with client_for(runtime, receipt_database, tmp_path, "maker") as (client, headers):
        install_owned_router(client)
        response = client.post(f"/api/v1/operational-fx-tax/invoices/{initial['source_id']}/revaluation-reversals", headers=headers,
            json={"command_id": "http-inverse", "original_revaluation_id": plan["id"], "period_id": "period", "posting_date": "2026-10-04", "reason": "HTTP explicit full inverse"})
        assert response.status_code == 200, response.text
        inverse = response.json()["plan"]
        assert inverse["snapshot"]["entry"]["reverses_posting_id"] == plan["posting_effect_id"]
    for name, operation in (("checker", "review"), ("poster", "post")):
        with client_for(runtime, receipt_database, tmp_path, name) as (client, headers):
            install_owned_router(client)
            response = client.post(f"/api/v1/operational-fx-tax/plans/{inverse['id']}/{operation}", headers=headers,
                json={"command_id": "http-inverse-" + operation, "expected_plan_digest": inverse["plan_digest"], "reason": "Independent inverse " + operation})
            assert response.status_code == 200, response.text
    assert native_balances(runtime)["AR"] == 14251 and native_balances(runtime)["UGAIN"] == 0
