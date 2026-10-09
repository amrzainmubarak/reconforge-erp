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
        PostgresFinanceCoreRepository(connection, rt.tenant).validate_entry(
            entry["id"], reason="Independent actual movement", actor_label=actor.username
        )
        reviewed = PostgresFinancePostingRepository(connection, rt.tenant).preview(entry["id"], actor=actor)
    with rt.actor("poster") as (connection, _, actor):
        PostgresFinancePostingRepository(connection, rt.tenant).post(
            entry["id"],
            command_id=number,
            expected_validation_digest=reviewed["current_content_digest"],
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
    with (
        rt.actor("poster") as (connection, _, actor),
        pytest.raises(FinancePostingError, match="complete reviewed source"),
    ):
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


def test_raw_reserved_owner_and_immutable_phase_acknowledgements_are_refused(reporting_runtime: ReceiptRuntime) -> None:
    from psycopg.errors import CheckViolation

    rt = reporting_runtime
    with pytest.raises(CheckViolation, match="Reserved OB1"), rt.actor("maker") as (connection, _, actor):
        PostgresFinanceCoreRepository(connection, rt.tenant).create_entry(
            entry_number="oB1-forged",
            organization_code="ORG",
            entity_code="ENTITY",
            period_id="period",
            journal_code="STOCK",
            posting_date="2026-10-01",
            description="Unowned reserved source",
            workspace="work",
            lines=[
                {"account_code": "CASH", "debit": "100", "credit": "0"},
                {"account_code": "EQUITY", "debit": "0", "credit": "100"},
            ],
            actor_label=actor.username,
        )
    plan = opening_cycle(rt)
    post_opening(rt, plan)
    with rt.actor("poster") as (connection, _, actor):
        for statement in (
            "UPDATE reconforge.financial_opening_plans SET payload=payload||'{\"amount_minor\":10001}'::jsonb WHERE tenant_id=%s",
            "DELETE FROM reconforge.financial_opening_links WHERE tenant_id=%s",
            "UPDATE reconforge.financial_reporting_commands SET result_json=result_json||'{\"amount_minor\":10001}'::jsonb WHERE tenant_id=%s",
        ):
            with pytest.raises(CheckViolation, match="immutable"), connection.transaction():
                connection.execute(statement, (rt.tenant,))
        with pytest.raises(CheckViolation, match="actual current owner phase"), connection.transaction():
            connection.execute(
                """INSERT INTO reconforge.financial_reporting_commands
                (tenant_id,workspace_id,command_id,operation,actor_id,request_digest,request_json,object_id,result_json)
                SELECT tenant_id,workspace_id,'RAW-LATE-PREPARE',operation,actor_id,request_digest,request_json,object_id,result_json
                FROM reconforge.financial_reporting_commands WHERE tenant_id=%s AND operation='prepare_opening'""",
                (rt.tenant,),
            )
        with pytest.raises(CheckViolation, match="acknowledged phase"), connection.transaction():
            connection.execute(
                """INSERT INTO reconforge.financial_reporting_commands
                (tenant_id,workspace_id,command_id,operation,actor_id,request_digest,request_json,object_id,result_json)
                SELECT tenant_id,workspace_id,'RAW-FORGED-RESULT',operation,actor_id,request_digest,request_json,object_id,result_json||'{"amount_minor":10001}'::jsonb
                FROM reconforge.financial_reporting_commands WHERE tenant_id=%s AND operation='post_opening'""",
                (rt.tenant,),
            )
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert (
            PostgresFinancialReportingRepository(connection, rt.tenant).get_opening(plan["id"], actor=actor)["status"]
            == "Posted"
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (rt.tenant,)
            ).fetchone()[0]
            == 1
        )


def test_new_opening_requires_the_current_semantics_of_its_reviewed_accounts(reporting_runtime: ReceiptRuntime) -> None:
    from tests.test_postgres_financial_reporting_api import opening_cycle_for_map

    rt = reporting_runtime
    mapping = map_cycle(rt)
    with PostgresTenantBoundary(rt.factory).transaction(rt.tenant) as connection:
        PostgresFinanceCoreRepository(connection, rt.tenant).upsert_account(
            account_code="EQUITY",
            name="Renamed current equity",
            account_type="Equity",
            normal_balance="Credit",
            chart_code="DEFAULT",
            workspace="work",
        )
    with pytest.raises(FinancePostingError) as rejected:
        opening_cycle_for_map(rt, mapping)
    assert rejected.value.code == "financial_reporting_state_conflict"
    assert getattr(rejected.value.__cause__, "sqlstate", None) == "23514"
    assert rejected.value.__cause__.diag.constraint_name == "financial_reporting_owner_phase"
    with rt.actor("maker") as (connection, _, actor):
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.financial_opening_plans WHERE tenant_id=%s", (rt.tenant,)
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.finance_entries WHERE tenant_id=%s", (rt.tenant,)
            ).fetchone()[0]
            == 0
        )
        assert (
            PostgresFinancialReportingRepository(connection, rt.tenant).get_map(mapping["id"], actor=actor)["status"]
            == "Reviewed"
        )


def test_opening_cannot_rewrite_retained_prior_financial_history(reporting_runtime: ReceiptRuntime) -> None:
    from tests.test_postgres_financial_reporting_api import opening_cycle_for_map

    rt = reporting_runtime
    manual(rt, "PRIOR-ACTUAL-CAPITAL", "CASH", "EQUITY", 10000, "2026-10-08")
    mapping = map_cycle(rt)
    with pytest.raises(FinancePostingError, match="retained financial posting history"):
        opening_cycle_for_map(rt, mapping)
    with rt.actor("poster") as (connection, _, actor):
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.financial_opening_plans WHERE tenant_id=%s", (rt.tenant,)
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (rt.tenant,)
            ).fetchone()[0]
            == 1
        )


def test_additive_installer_preserves_populated_sources_and_refuses_destructive_downgrade(
    reporting_runtime: ReceiptRuntime,
) -> None:
    import psycopg
    from psycopg.errors import RaiseException

    from reconforge.infrastructure.postgres_financial_reporting_schema import (
        DOWNGRADE_SQL,
        install_postgres_financial_reporting_schema,
    )
    from tests.test_postgres_financial_reporting_api import retained_financial_business

    rt = reporting_runtime
    post_opening(rt, opening_cycle(rt))
    before = retained_financial_business(rt)
    with psycopg.connect(rt.admin_dsn) as admin:
        install_postgres_financial_reporting_schema(admin)
        install_postgres_financial_reporting_schema(admin)
    assert retained_financial_business(rt) == before
    with pytest.raises(RaiseException, match="forward recovery"), psycopg.connect(rt.admin_dsn) as admin:
        admin.execute(DOWNGRADE_SQL)
    assert retained_financial_business(rt) == before


def test_empty_downgrade_and_reupgrade_restore_scoped_invoker_guards(receipt_database: tuple[str, str]) -> None:
    import subprocess
    import sys
    from pathlib import Path
    from uuid import uuid4

    import psycopg
    from psycopg import sql

    database = "reconforge_fr_migration_" + uuid4().hex[:12]
    original = psycopg.conninfo.conninfo_to_dict(receipt_database[0])
    control_dsn = psycopg.conninfo.make_conninfo(**{**original, "dbname": "postgres"})
    admin_dsn = psycopg.conninfo.make_conninfo(**{**original, "dbname": database})
    app_settings = psycopg.conninfo.conninfo_to_dict(receipt_database[1])
    app_dsn = psycopg.conninfo.make_conninfo(**{**app_settings, "dbname": database})
    with psycopg.connect(control_dsn, autocommit=True) as control:
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        for verb, target in (
            ("upgrade", "0112_pg_financial_reporting"),
            ("downgrade", "0111_pg_procurement_operations"),
            ("upgrade", "0112_pg_financial_reporting"),
        ):
            subprocess.run(
                [sys.executable, "-m", "alembic", verb, target],
                cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, "RECONFORGE_POSTGRES_DSN": admin_dsn},
                check=True,
                timeout=180,
            )
            with psycopg.connect(admin_dsn) as admin:
                assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == target
                installed = admin.execute(
                    "SELECT to_regclass('reconforge.financial_opening_plans') IS NOT NULL"
                ).fetchone()[0]
                assert installed is (verb == "upgrade")
                if installed:
                    assert (
                        admin.execute(
                            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='reconforge' AND c.relname=ANY(%s) AND c.relrowsecurity AND c.relforcerowsecurity",
                            (
                                [
                                    "financial_reporting_maps",
                                    "financial_reporting_map_reviews",
                                    "financial_opening_plans",
                                    "financial_opening_reviews",
                                    "financial_opening_links",
                                    "financial_reporting_commands",
                                ],
                            ),
                        ).fetchone()[0]
                        == 6
                    )
                    assert (
                        admin.execute(
                            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='reconforge' AND p.proname LIKE 'fr_%%' AND p.prosecdef"
                        ).fetchone()[0]
                        == 0
                    )
        with psycopg.connect(admin_dsn) as admin:
            admin.execute(
                sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(app_settings["user"]))
            )
            admin.execute(
                sql.SQL("GRANT SELECT ON reconforge.financial_opening_plans TO {}").format(
                    sql.Identifier(app_settings["user"])
                )
            )
        with psycopg.connect(app_dsn) as application:
            assert tuple(
                application.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            ) == (False, False)
            assert tuple(
                application.execute(
                    "SELECT has_table_privilege(current_user,'reconforge.financial_opening_plans','SELECT'),has_table_privilege(current_user,'reconforge.financial_opening_plans','INSERT'),has_table_privilege(current_user,'reconforge.financial_opening_plans','UPDATE'),has_table_privilege(current_user,'reconforge.financial_opening_plans','DELETE')"
                ).fetchone()
            ) == (True, False, False, False)
    finally:
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            assert control.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None
