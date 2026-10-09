"""Actual restricted PostgreSQL asset lifecycle and independent GL oracles."""

from dataclasses import replace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.fixed_assets import AssetAcquisition
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_fixed_assets import PostgresFixedAssetsRepository
from tests.test_postgres_inventory_receipt_posting import (
    ReceiptRuntime,
    create_receipt_runtime,
    pytestmark,
    receipt_database,
)

__all__ = ["pytestmark", "receipt_database"]


def seed_asset_masters(runtime: ReceiptRuntime) -> ReceiptRuntime:
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org") as connection:
        finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
        for code, kind in (("FIXED", "Asset"), ("ACCUM", "Asset"), ("DEPRECIATION", "Expense"), ("CASH", "Asset"), ("GAIN", "Income"), ("LOSS", "Expense")):
            finance.upsert_account(account_code=code, name=code, account_type=kind, chart_code="DEFAULT", workspace="work")
        for identifier, year, month, start, end in (("nov", 2026, 11, "2026-11-01", "2026-11-30"), ("dec", 2026, 12, "2026-12-01", "2026-12-31"), ("jan", 2027, 1, "2027-01-01", "2027-01-31")):
            connection.execute("""INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number,application_workspace_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,'work')""", (runtime.tenant, identifier, identifier, start, end, year, month))
            connection.execute("INSERT INTO reconforge.master_data_workspace_periods(tenant_id,workspace_id,period_id) VALUES(%s,'work',%s)", (runtime.tenant, identifier))
    return runtime


@pytest.fixture
def asset_runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    return seed_asset_masters(create_receipt_runtime(receipt_database))


def acquisition(number: str = "MACHINE-1") -> AssetAcquisition:
    return AssetAcquisition(workspace_id="work", organization_id="org", legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY",
        asset_number=number, name="Synthetic production machine", journal_code="STOCK", period_id="period", posting_date="2026-10-01",
        in_service_date="2026-10-01", cost_minor=10101, salvage_minor=1001, useful_life_months=3, asset_account_code="FIXED",
        accumulated_account_code="ACCUM", expense_account_code="DEPRECIATION", cash_account_code="CASH", gain_account_code="GAIN",
        loss_account_code="LOSS", reason="Reviewed synthetic acquisition")


def acquire(runtime: ReceiptRuntime, request: AssetAcquisition | None = None) -> dict[str, Any]:
    request = request or acquisition()
    with runtime.actor("maker") as (connection, _, actor):
        repository = PostgresFixedAssetsRepository(connection, runtime.tenant)
        result = repository.acquire(request, command_id="acquire-" + request.asset_number, actor=actor)
        assert repository.acquire(request, command_id="acquire-" + request.asset_number, actor=actor) == result
        return result


def finish(runtime: ReceiptRuntime, plan: dict[str, Any]) -> dict[str, Any]:
    with runtime.actor("checker") as (connection, _, actor):
        repository = PostgresFixedAssetsRepository(connection, runtime.tenant)
        args = {"expected_plan_digest": plan["plan_digest"], "command_id": "review-" + plan["id"], "reason": "Independent asset equation review", "actor": actor}
        result = repository.review(plan["id"], **args)
        assert repository.review(plan["id"], **args) == result
    with runtime.actor("poster") as (connection, _, actor):
        repository = PostgresFixedAssetsRepository(connection, runtime.tenant)
        args = {"expected_plan_digest": plan["plan_digest"], "command_id": "post-" + plan["id"], "reason": "Independent asset publication", "actor": actor}
        posted = repository.post(plan["id"], **args)
        assert repository.post(plan["id"], **args) == posted
        assert repository.get_plan(plan["id"], actor=actor) == posted
        return posted


def operation(runtime: ReceiptRuntime, asset_id: str, *, kind: str, date: str, period: str,
              month: str = "", proceeds: int = 0) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        return PostgresFixedAssetsRepository(connection, runtime.tenant).prepare(asset_id, kind=kind, period_id=period,
            posting_date=date, through_month=month, proceeds_minor=proceeds, reason="Exact asset lifecycle operation",
            command_id=kind + "-" + date, actor=actor)


def balances(runtime: ReceiptRuntime) -> dict[str, int]:
    with runtime.actor("poster") as (connection, _, _):
        assert dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == {"rolsuper": False, "rolbypassrls": False}
        rows = connection.execute("""SELECT a.account_code,sum(l.debit_minor-l.credit_minor)::bigint AS amount FROM reconforge.finance_posting_effects effect
            JOIN reconforge.finance_entry_lines l ON l.tenant_id=effect.tenant_id AND l.entry_id=effect.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
            WHERE effect.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()
        return {row["account_code"]: row["amount"] for row in rows}


def test_acquisition_two_cumulative_depreciations_and_gain_disposal(asset_runtime: ReceiptRuntime) -> None:
    runtime = asset_runtime
    initial = finish(runtime, acquire(runtime))
    first = finish(runtime, operation(runtime, initial["asset_id"], kind="depreciate", date="2026-11-01", period="nov", month="2026-10"))
    assert first["amount_minor"] == 3033
    catchup = finish(runtime, operation(runtime, initial["asset_id"], kind="depreciate", date="2027-01-01", period="jan", month="2026-12"))
    assert catchup["amount_minor"] == 6067
    disposal = finish(runtime, operation(runtime, initial["asset_id"], kind="dispose", date="2027-01-02", period="jan", proceeds=1500))
    assert disposal["amount_minor"] == 1001
    assert balances(runtime) == {"FIXED": 0, "ACCUM": 0, "DEPRECIATION": 9100, "CASH": -8601, "GAIN": -499}
    with runtime.actor("poster") as (connection, _, actor):
        detail = PostgresFixedAssetsRepository(connection, runtime.tenant).get(initial["asset_id"], actor=actor)
        assert detail["status"] == "Disposed" and detail["carrying_minor"] == 0 and detail["accumulated_minor"] == 9100
        assert len(detail["plans"]) == 4 and all(plan["status"] == "Posted" for plan in detail["plans"])


def test_fully_depreciated_zero_carrying_disposal_retains_positive_turnover(asset_runtime: ReceiptRuntime) -> None:
    runtime = asset_runtime
    initial = finish(runtime, acquire(runtime, replace(acquisition(), cost_minor=101, salvage_minor=0, useful_life_months=1)))
    finish(runtime, operation(runtime, initial["asset_id"], kind="depreciate", date="2026-11-01", period="nov", month="2026-10"))
    disposal = finish(runtime, operation(runtime, initial["asset_id"], kind="dispose", date="2026-11-02", period="nov"))
    assert disposal["amount_minor"] == 0
    assert balances(runtime) == {"FIXED": 0, "ACCUM": 0, "DEPRECIATION": 101, "CASH": -101}


def test_no_depreciation_or_disposal_before_posted_acquisition_or_after_disposal(asset_runtime: ReceiptRuntime) -> None:
    runtime = asset_runtime
    plan = acquire(runtime)
    with pytest.raises(FinancePostingError, match="pending"):
        operation(runtime, plan["asset_id"], kind="dispose", date="2026-10-03", period="period")
    finish(runtime, plan)
    finish(runtime, operation(runtime, plan["asset_id"], kind="dispose", date="2026-10-03", period="period", proceeds=2000))
    with pytest.raises(FinancePostingError, match="undisposed"):
        operation(runtime, plan["asset_id"], kind="depreciate", date="2026-11-01", period="nov", month="2026-10")
    assert balances(runtime) == {"FIXED": 0, "CASH": -8101, "LOSS": 8101}


def test_depreciation_month_reuse_and_regressing_dates_are_refused(asset_runtime: ReceiptRuntime) -> None:
    runtime = asset_runtime
    plan = finish(runtime, acquire(runtime))
    finish(runtime, operation(runtime, plan["asset_id"], kind="depreciate", date="2026-11-01", period="nov", month="2026-10"))
    with pytest.raises(FinancePostingError, match="No new"):
        operation(runtime, plan["asset_id"], kind="depreciate", date="2026-11-02", period="nov", month="2026-10")
    with pytest.raises(FinancePostingError, match="regress"):
        operation(runtime, plan["asset_id"], kind="dispose", date="2026-10-30", period="period", proceeds=3000)


def test_generic_review_post_and_direct_sql_source_tamper_are_refused(asset_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = asset_runtime
    plan = acquire(runtime)
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("checker") as (connection, _, actor):
        PostgresFinanceCoreRepository(connection, runtime.tenant).validate_entry(plan["entry_id"], reason="Detached review", actor_label=actor.username)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with runtime.actor("checker") as (connection, _, actor):
        reviewed = PostgresFixedAssetsRepository(connection, runtime.tenant).review(plan["id"], expected_plan_digest=plan["plan_digest"],
            command_id="review", reason="Independent review", actor=actor)
    with runtime.actor("poster") as (connection, _, actor), pytest.raises(FinancePostingError, match="owner"):
        PostgresFinancePostingRepository(connection, runtime.tenant).post(plan["entry_id"], expected_validation_digest=plan["validation_digest"], command_id="detach", reason="Detached publication", actor=actor)
    for statement in (
        "UPDATE reconforge.fixed_asset_plans SET phase=2 WHERE tenant_id=%s",
        "UPDATE reconforge.fixed_assets SET payload=jsonb_set(payload,'{cost_minor}','1') WHERE tenant_id=%s",
        "DELETE FROM reconforge.fixed_asset_reviews WHERE tenant_id=%s",
        "UPDATE reconforge.fixed_asset_commands SET response_json='{}' WHERE tenant_id=%s",
    ):
        with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("poster") as (connection, _, _):
            connection.execute(statement, (runtime.tenant,))
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with runtime.actor("poster") as (connection, _, actor):
        assert PostgresFixedAssetsRepository(connection, runtime.tenant).get_plan(plan["id"], actor=actor) == reviewed


def test_self_review_and_both_non_independent_posters_are_denied(asset_runtime: ReceiptRuntime) -> None:
    runtime = asset_runtime
    plan = acquire(runtime)
    with runtime.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError, match="independent"):
        PostgresFixedAssetsRepository(connection, runtime.tenant).review(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="self", reason="Self review", actor=actor)
    with runtime.actor("checker") as (connection, _, actor):
        PostgresFixedAssetsRepository(connection, runtime.tenant).review(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="review", reason="Independent review", actor=actor)
    for username in ("maker", "checker"):
        with runtime.actor(username) as (connection, _, actor), pytest.raises(FinancePostingError, match="third"):
            PostgresFixedAssetsRepository(connection, runtime.tenant).post(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="self-post-" + username, reason="Post attempt", actor=actor)


def test_parallel_same_command_produces_one_asset_and_one_native_effect(asset_runtime: ReceiptRuntime) -> None:
    from concurrent.futures import ThreadPoolExecutor
    runtime = asset_runtime
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _: acquire(runtime), range(2)))
    assert first == second
    with runtime.actor("checker") as (connection, _, actor):
        PostgresFixedAssetsRepository(connection, runtime.tenant).review(first["id"], expected_plan_digest=first["plan_digest"], command_id="review", reason="Independent review", actor=actor)
    def post_once(_: int) -> dict[str, Any]:
        with runtime.actor("poster") as (connection, _, actor):
            return PostgresFixedAssetsRepository(connection, runtime.tenant).post(first["id"], expected_plan_digest=first["plan_digest"], command_id="parallel-post", reason="Native publication", actor=actor)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(post_once, range(2)))
    assert results[0] == results[1]
    with runtime.actor("poster") as (connection, _, _):
        assert connection.execute("SELECT count(*) n FROM reconforge.fixed_assets WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1


def test_closed_period_and_changed_acquisition_retry_are_refused(asset_runtime: ReceiptRuntime) -> None:
    runtime = asset_runtime
    first = acquire(runtime)
    with runtime.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError, match="another"):
        PostgresFixedAssetsRepository(connection, runtime.tenant).acquire(replace(acquisition(), cost_minor=10102), command_id="acquire-MACHINE-1", actor=actor)
    finish(runtime, first)
    with runtime.actor("maker") as (connection, _, _):
        connection.execute("UPDATE reconforge.fiscal_periods SET status='Closed' WHERE tenant_id=%s AND id='nov'", (runtime.tenant,))
    with pytest.raises(Exception, match="Open|open"):
        operation(runtime, first["asset_id"], kind="depreciate", date="2026-11-01", period="nov", month="2026-10")
