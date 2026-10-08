"""Mandatory configured PostgreSQL: opening, reviewed classification and real statements."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.financial_reporting import AccountClassification, OpeningLine, OpeningPreparation, ReportingScope
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, create_receipt_runtime, receipt_database

__all__ = ["receipt_database"]
pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="requires the configured native PostgreSQL fixture; configured gate executes every case",
)
SCOPE = ReportingScope("work", "org", "entity")


@pytest.fixture
def reporting_runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    rt = create_receipt_runtime(receipt_database)
    with PostgresTenantBoundary(rt.factory).transaction(rt.tenant) as connection:
        finance = PostgresFinanceCoreRepository(connection, rt.tenant)
        for code, kind in (
            ("CASH", "Asset"),
            ("SAVING", "Asset"),
            ("EQUITY", "Equity"),
            ("REVENUE", "Income"),
            ("COST", "Expense"),
        ):
            finance.upsert_account(
                account_code=code,
                name=code,
                account_type=kind,
                normal_balance="Credit" if kind in {"Equity", "Income"} else "Debit",
                chart_code="DEFAULT",
                workspace="work",
            )
        identities = PostgresIdentityRepository(connection)
        for permission in ("finance_core.read", "finance_core.manage", "finance_core.validate", "finance_core.post"):
            identities.create_permission(tenant_id=rt.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=rt.tenant, role_name="receipt-operator", permission_name=permission)
        connection.execute(
            "INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number,application_workspace_id) VALUES(%s,'nov','2026-11','2026-11-01','2026-11-30',2026,11,'work')",
            (rt.tenant,),
        )
        connection.execute(
            "INSERT INTO reconforge.master_data_workspace_periods(tenant_id,workspace_id,period_id) VALUES(%s,'work','nov')",
            (rt.tenant,),
        )
    return rt


def map_cycle(rt: ReceiptRuntime) -> dict[str, Any]:
    with rt.actor("maker") as (connection, _, actor):
        result = PostgresFinancialReportingRepository(connection, rt.tenant).prepare_map(
            SCOPE,
            name="Reviewed synthetic chart",
            accounts=[
                AccountClassification("CASH", "CurrentAsset", True),
                AccountClassification("SAVING", "CurrentAsset", True),
                AccountClassification("EQUITY", "Equity"),
                AccountClassification("REVENUE", "Income"),
                AccountClassification("COST", "Expense"),
            ],
            command_id="map-prepare",
            actor=actor,
        )
    with rt.actor("checker") as (connection, _, actor):
        return PostgresFinancialReportingRepository(connection, rt.tenant).review_map(
            result["id"],
            expected_digest=result["map_digest"],
            reason="Independent classification",
            command_id="map-review",
            actor=actor,
        )


def opening_cycle(rt: ReceiptRuntime) -> dict[str, Any]:
    mapping = map_cycle(rt)
    with rt.actor("maker") as (connection, _, actor):
        plan = PostgresFinancialReportingRepository(connection, rt.tenant).prepare_opening(
            OpeningPreparation(
                SCOPE,
                mapping["id"],
                "ORG",
                "ENTITY",
                "period",
                "STOCK",
                "2026-10-01",
                "Initial audited balances",
                (OpeningLine("CASH", 10000, 0), OpeningLine("EQUITY", 0, 10000)),
            ),
            command_id="opening-prepare",
            actor=actor,
        )
    with rt.actor("checker") as (connection, _, actor):
        return PostgresFinancialReportingRepository(connection, rt.tenant).review_opening(
            plan["id"],
            expected_digest=plan["plan_digest"],
            reason="Independent opening review",
            command_id="opening-review",
            actor=actor,
        )


def post_opening(rt: ReceiptRuntime, plan: dict[str, Any]) -> dict[str, Any]:
    with rt.actor("poster") as (connection, _, actor):
        return PostgresFinancialReportingRepository(connection, rt.tenant).post_opening(
            plan["id"],
            expected_digest=plan["plan_digest"],
            reason="Post initial balances",
            command_id="opening-post",
            actor=actor,
        )


def manual(rt: ReceiptRuntime, number: str, debit: str, credit: str, amount: int, day: str) -> None:
    with rt.actor("maker") as (connection, _, actor):
        entry = PostgresFinanceCoreRepository(connection, rt.tenant).create_entry(
            entry_number=number,
            organization_code="ORG",
            entity_code="ENTITY",
            period_id="period",
            journal_code="STOCK",
            posting_date=day,
            description=number,
            lines=[
                {"account_code": debit, "debit": f"{amount // 100}.{amount % 100:02d}", "credit": "0"},
                {"account_code": credit, "debit": "0", "credit": f"{amount // 100}.{amount % 100:02d}"},
            ],
            workspace="work",
            actor_label=actor.username,
        )
    with rt.actor("checker") as (connection, _, actor):
        reviewed = PostgresFinanceCoreRepository(connection, rt.tenant).validate_entry(
            entry["id"], reason="Independent actual movement", actor_label=actor.username
        )
    with rt.actor("poster") as (connection, _, actor):
        PostgresFinancePostingRepository(connection, rt.tenant).post(
            entry["id"],
            command_id=number,
            expected_validation_digest=reviewed["validation_digest"],
            reason="Actual movement",
            actor=actor,
        )


def test_real_opening_asof_balance_sheet_income_cash_transfer_and_next_period(
    reporting_runtime: ReceiptRuntime,
) -> None:
    rt = reporting_runtime
    plan = opening_cycle(rt)
    effect = post_opening(rt, plan)
    assert effect["status"] == "Posted"
    manual(rt, "SALE", "CASH", "REVENUE", 3000, "2026-10-08")
    manual(rt, "EXPENSE", "COST", "CASH", 1000, "2026-10-09")
    manual(rt, "TRANSFER", "SAVING", "CASH", 500, "2026-10-10")
    with rt.actor("poster") as (connection, _, actor):
        role = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        assert tuple(role) == (False, False)
        repository = PostgresFinancialReportingRepository(connection, rt.tenant)
        early = repository.report(
            map_id=plan["map_id"],
            period_id="period",
            as_of_date="2026-10-08",
            organization_code="ORG",
            entity_code="ENTITY",
            actor=actor,
        )
        assert early["balance_sheet"] == {
            "assets_minor": 13000,
            "liabilities_minor": 0,
            "equity_minor": 10000,
            "accumulated_unclosed_result_minor": 3000,
            "balanced": True,
        }
        assert early["income_statement"] == {"income_minor": 3000, "expense_minor": 0, "result_minor": 3000}
        full = repository.report(
            map_id=plan["map_id"],
            period_id="period",
            as_of_date="2026-10-31",
            organization_code="ORG",
            entity_code="ENTITY",
            actor=actor,
        )
        assert full["income_statement"]["result_minor"] == 2000
        assert full["cash_movements"]["closing_minor"] == 12000
        assert [row["movement_kind"] for row in full["cash_movements"]["movements"]] == [
            "Inflow",
            "Inflow",
            "Outflow",
            "InternalTransfer",
        ]
        assert full == repository.report(
            map_id=plan["map_id"],
            period_id="period",
            as_of_date="2026-10-31",
            organization_code="ORG",
            entity_code="ENTITY",
            actor=actor,
        )
        next_period = repository.report(
            map_id=plan["map_id"],
            period_id="nov",
            as_of_date="2026-11-15",
            organization_code="ORG",
            entity_code="ENTITY",
            actor=actor,
        )
        assert next_period["cash_movements"]["opening_minor"] == 12000
        assert next_period["cash_movements"]["activity_minor"] == 0
        assert next_period["income_statement"]["result_minor"] == 0
        assert repository.catalog(SCOPE, actor=actor)["periods"][0]["name"] == "2026-10"


def test_six_exact_opening_retries_have_one_native_effect(reporting_runtime: ReceiptRuntime) -> None:
    rt = reporting_runtime
    plan = opening_cycle(rt)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: post_opening(rt, plan), range(6)))
    assert all(row == results[0] for row in results)
    with rt.actor("poster") as (connection, _, actor):
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (rt.tenant,)
            ).fetchone()[0]
            == 1
        )


def test_native_detached_review_and_generic_post_and_selfapproval_are_refused(
    reporting_runtime: ReceiptRuntime,
) -> None:
    from psycopg.errors import CheckViolation

    rt = reporting_runtime
    mapping = map_cycle(rt)
    with rt.actor("maker") as (connection, _, actor):
        repo = PostgresFinancialReportingRepository(connection, rt.tenant)
        plan = repo.prepare_opening(
            OpeningPreparation(
                SCOPE,
                mapping["id"],
                "ORG",
                "ENTITY",
                "period",
                "STOCK",
                "2026-10-01",
                "Initial",
                (OpeningLine("CASH", 10000, 0), OpeningLine("EQUITY", 0, 10000)),
            ),
            command_id="opening-prepare",
            actor=actor,
        )
        with pytest.raises(FinancePostingError, match="independent"):
            repo.review_opening(
                plan["id"], expected_digest=plan["plan_digest"], reason="Self", command_id="self", actor=actor
            )
    with pytest.raises(CheckViolation), rt.actor("checker") as (connection, _, actor):
        PostgresFinanceCoreRepository(connection, rt.tenant).validate_entry(
            plan["entry_id"], reason="Detached owner", actor_label=actor.username
        )
    with rt.actor("checker") as (connection, _, actor):
        repo = PostgresFinancialReportingRepository(connection, rt.tenant)
        repo.review_opening(
            plan["id"],
            expected_digest=plan["plan_digest"],
            reason="Actual owner",
            command_id="opening-review",
            actor=actor,
        )
    with rt.actor("poster") as (connection, _, actor), pytest.raises(FinancePostingError, match="complete reviewed source"):
        PostgresFinancePostingRepository(connection, rt.tenant).post(
            plan["entry_id"],
            command_id="generic",
            expected_validation_digest=plan["validation_digest"],
            reason="Detached source",
            actor=actor,
        )
    post_opening(rt, plan)


def test_late_command_failure_rolls_back_native_gl_and_source_link(
    reporting_runtime: ReceiptRuntime, monkeypatch: Any
) -> None:
    rt = reporting_runtime
    plan = opening_cycle(rt)
    with rt.actor("poster") as (connection, _, actor):
        repo = PostgresFinancialReportingRepository(connection, rt.tenant)
        remember = repo._remember

        def fail_late(*args: Any, **kwargs: Any) -> None:
            remember(*args, **kwargs)
            raise RuntimeError("synthetic late source command failure")

        with monkeypatch.context() as patch:
            patch.setattr(repo, "_remember", fail_late)
            with pytest.raises(RuntimeError, match="synthetic late"):
                repo.post_opening(
                    plan["id"],
                    expected_digest=plan["plan_digest"],
                    reason="Post initial balances",
                    command_id="opening-post",
                    actor=actor,
                )
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (rt.tenant,)
            ).fetchone()[0]
            == 0
        )
        assert repo.get_opening(plan["id"], actor=actor)["status"] == "Reviewed"
    assert post_opening(rt, plan)["status"] == "Posted"
