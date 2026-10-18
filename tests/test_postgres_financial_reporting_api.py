"""Real factory, HTTP-origin/auth and PostgreSQL proofs; wire TLS belongs to E2E."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from tests.test_postgres_financial_reporting import (
    manual,
    map_cycle,
    pytestmark,
    receipt_database,
    reporting_runtime,
)
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_operational_finance_api import client_for

__all__ = ["pytestmark", "receipt_database", "reporting_runtime"]
ROOT = "/api/v1/financial-reporting"


def retained_financial_business(rt: ReceiptRuntime) -> dict[str, Any]:
    from psycopg import sql

    tables = (
        "financial_reporting_maps",
        "financial_reporting_map_reviews",
        "financial_opening_plans",
        "financial_opening_reviews",
        "financial_opening_links",
        "financial_reporting_commands",
        "finance_entries",
        "finance_entry_lines",
        "finance_entry_line_dimensions",
        "finance_posting_effects",
        "finance_posting_commands",
    )
    with PostgresTenantBoundary(rt.factory).transaction(
        rt.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity"
    ) as connection:
        assert tuple(
            connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        ) == (False, False)
        return {
            table: connection.execute(
                sql.SQL(
                    "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb) FROM reconforge.{} t WHERE tenant_id=%s"
                ).format(sql.Identifier(table)),
                (rt.tenant,),
            ).fetchone()[0]
            for table in tables
        }


def test_normal_factory_reviewed_opening_and_asof_statements_preserve_money_and_exact_replay(
    reporting_runtime: ReceiptRuntime, receipt_database: tuple[str, str], tmp_path: Path
) -> None:
    rt = reporting_runtime
    with client_for(rt, receipt_database, tmp_path, "maker") as (client, headers):
        assert client.get(ROOT + "/catalog", headers=headers).json()["catalog"]["currency_code"] == "USD"
        prepared = client.post(
            ROOT + "/maps",
            headers=headers,
            json={
                "command_id": "HTTP-MAP",
                "name": "Actual API classification",
                "accounts": [
                    {"account_code": "CASH", "section": "CurrentAsset", "is_cash": True},
                    {"account_code": "EQUITY", "section": "Equity"},
                    {"account_code": "REVENUE", "section": "Income"},
                    {"account_code": "COST", "section": "Expense"},
                ],
            },
        )
        assert prepared.status_code == 200, prepared.text
        mapping = prepared.json()["map"]
    with client_for(rt, receipt_database, tmp_path, "checker") as (client, headers):
        reviewed = client.post(
            ROOT + "/maps/" + mapping["id"] + "/review",
            headers=headers,
            json={
                "command_id": "HTTP-MAP-REVIEW",
                "expected_digest": mapping["map_digest"],
                "reason": "Independent mapped classifications",
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["map"]["status"] == "Reviewed"
        empty = client.get(
            ROOT + "/statements",
            headers=headers,
            params={"map_id": mapping["id"], "period_id": "period", "as_of_date": "2026-10-08"},
        )
        assert empty.status_code == 200, empty.text
        assert empty.json()["statements"]["currency_policy"] is None
        assert empty.json()["statements"]["effect_count"] == 0
    with client_for(rt, receipt_database, tmp_path, "maker") as (client, headers):
        prepared = client.post(
            ROOT + "/openings",
            headers=headers,
            json={
                "command_id": "HTTP-OPENING",
                "map_id": mapping["id"],
                "period_id": "period",
                "journal_code": "STOCK",
                "posting_date": "2026-10-01",
                "reason": "Initial confirmed balances",
                "lines": [
                    {"account_code": "CASH", "debit_minor": "10000", "credit_minor": "0"},
                    {"account_code": "EQUITY", "debit_minor": "0", "credit_minor": "10000"},
                ],
            },
        )
        assert prepared.status_code == 200, prepared.text
        plan = prepared.json()["opening"]
        assert plan["status"] == "Draft" and plan["amount_minor"] == "10000"
    for username, phase, expected_status in (("checker", "review", "Reviewed"), ("poster", "post", "Posted")):
        with client_for(rt, receipt_database, tmp_path, username) as (client, headers):
            body = {
                "command_id": "HTTP-OPENING-" + phase,
                "expected_digest": plan["plan_digest"],
                "reason": "Independent opening " + phase,
            }
            path = ROOT + "/openings/" + plan["id"] + "/" + phase
            response = client.post(path, headers=headers, json=body)
            assert response.status_code == 200, response.text
            plan = response.json()["opening"]
            assert plan["status"] == expected_status
            before = retained_financial_business(rt)
            replay = client.post(path, headers=headers, json=body)
            assert replay.status_code == 200 and replay.json()["opening"] == plan
            assert retained_financial_business(rt) == before
    manual(rt, "HTTP-SALE", "CASH", "REVENUE", 3000, "2026-10-08")
    manual(rt, "HTTP-LATER-EXPENSE", "COST", "CASH", 1000, "2026-10-09")
    with client_for(rt, receipt_database, tmp_path, "poster") as (client, headers):
        before = retained_financial_business(rt)
        response = client.get(
            ROOT + "/statements",
            headers=headers,
            params={"map_id": mapping["id"], "period_id": "period", "as_of_date": "2026-10-08"},
        )
        assert response.status_code == 200, response.text
        report = response.json()["statements"]
        assert report["balance_sheet"] == {
            "assets_minor": "13000",
            "liabilities_minor": "0",
            "equity_minor": "10000",
            "accumulated_unclosed_result_minor": "3000",
            "balanced": True,
        }
        assert report["income_statement"] == {"income_minor": "3000", "expense_minor": "0", "result_minor": "3000"}
        assert report["effect_count"] == 2
        assert report["cash_movements"]["closing_minor"] == "13000"
        assert all(
            line["posting_date"] <= "2026-10-08"
            for row in report["trial_balance"]["accounts"]
            for line in row["postings"]
        )
        assert retained_financial_business(rt) == before


def test_normal_factory_current_stepup_scope_and_human_separation_precede_opening_mutation(
    reporting_runtime: ReceiptRuntime, receipt_database: tuple[str, str], tmp_path: Path
) -> None:
    rt = reporting_runtime
    mapping = map_cycle(rt)
    plan = opening_cycle_for_map(rt, mapping)
    path = ROOT + "/openings/" + plan["id"] + "/review"
    body = {
        "command_id": "HTTP-SELF",
        "expected_digest": plan["plan_digest"],
        "reason": "Must remain an independent review",
    }
    with client_for(rt, receipt_database, tmp_path, "maker") as (client, headers):
        before = retained_financial_business(rt)
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "financial_reporting_review_invalid"
        assert retained_financial_business(rt) == before
    with client_for(rt, receipt_database, tmp_path, "checker", step_up=False) as (client, headers):
        before = retained_financial_business(rt)
        response = client.post(path, headers=headers, json={**body, "command_id": "HTTP-NO-STEPUP"})
        assert response.status_code == 403, response.text
        assert retained_financial_business(rt) == before
    with client_for(rt, receipt_database, tmp_path, "checker") as (client, headers):
        before = retained_financial_business(rt)
        denied = client.post(path, headers={**headers, "X-ReconForge-Legal-Entity": "ungranted"}, json=body)
        assert denied.status_code == 403, denied.text
        assert retained_financial_business(rt) == before


def opening_cycle_for_map(rt: ReceiptRuntime, mapping: dict[str, Any]) -> dict[str, Any]:
    from reconforge.domain.financial_reporting import OpeningLine, OpeningPreparation
    from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
    from tests.test_postgres_financial_reporting import SCOPE

    with rt.actor("maker") as (connection, _, actor):
        return PostgresFinancialReportingRepository(connection, rt.tenant).prepare_opening(
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
