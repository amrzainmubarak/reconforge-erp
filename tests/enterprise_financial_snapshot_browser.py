"""Real immutable GL sources and an independent oracle for snapshot Studio acceptance."""

from typing import Any

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
from tests.erp_browser_seed import seed_erp_browser_principals
from tests.gfo_receipt_browser_seed import seed_receipt_browser
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

AMOUNTS = (9_007_199_254_740_993,) + tuple((ordinal * 37 % 997) + 1 for ordinal in range(1, 25))


def financial_snapshot_oracle() -> dict[str, Any]:
    """Expected values derive from the generator, independently of the ledger/report."""
    total = str(sum(AMOUNTS))
    return {"effect_count": len(AMOUNTS), "line_count": 2 * len(AMOUNTS), "assets_minor": total,
            "liabilities_minor": "0", "equity_minor": "0", "result_minor": total,
            "income_minor": total, "expense_minor": "0", "cash_minor": total}


def seed_financial_snapshot_browser(admin_dsn: str, app_dsn: str) -> ReceiptRuntime:
    """Isolated synthetic tenant; credentials stay in memory and never enter the oracle."""
    runtime = seed_receipt_browser(admin_dsn, app_dsn)
    seed_erp_browser_principals(runtime)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org") as connection:
        finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
        for code, kind, normal in (("CASH", "Asset", "Debit"), ("REVENUE", "Income", "Credit")):
            finance.upsert_account(account_code=code, name=code, account_type=kind, normal_balance=normal,
                                   chart_code="DEFAULT", workspace="work")
    entries: list[str] = []
    seals: list[str] = []
    with runtime.actor("browser-maker") as (connection, _, actor):
        finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
        for ordinal, amount in enumerate(AMOUNTS):
            major = f"{amount // 100}.{amount % 100:02d}"
            entries.append(finance.create_entry(entry_number=f"BROWSER-FRS-{ordinal:03d}", organization_code="ORG",
                entity_code="ENTITY", period_id="period", journal_code="STOCK", posting_date="2026-10-09",
                description="Synthetic independently reviewed browser report contribution", workspace="work",
                actor_label=actor.username, lines=[{"account_code": "CASH", "debit": major, "credit": "0"},
                                                 {"account_code": "REVENUE", "debit": "0", "credit": major}])["id"])
    with runtime.actor("browser-checker") as (connection, _, actor):
        finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
        posting = PostgresFinancePostingRepository(connection, runtime.tenant)
        for identifier in entries:
            finance.validate_entry(identifier, reason="Independent native source review", actor_label=actor.username)
            seals.append(posting.preview(identifier, actor=actor)["current_content_digest"])
    with runtime.actor("browser-poster") as (connection, _, actor):
        posting = PostgresFinancePostingRepository(connection, runtime.tenant)
        for ordinal, (identifier, seal) in enumerate(zip(entries, seals, strict=True)):
            posting.post(identifier, command_id=f"browser-frs-source-{ordinal:03d}", expected_validation_digest=seal,
                         reason="Third human publishes exact browser report source", actor=actor)
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s",
                                  (runtime.tenant,)).fetchone()["n"] == len(AMOUNTS)
    return runtime


def verify_financial_snapshot_browser(runtime: ReceiptRuntime) -> dict[str, Any]:
    """Read retained browser writes and verify complete source/evidence without new effects."""
    with runtime.actor("browser-poster") as (connection, _, actor):
        captured = connection.execute("SELECT id FROM reconforge.financial_report_captures WHERE tenant_id=%s",
                                      (runtime.tenant,)).fetchall()
        assert len(captured) == 1, "Exact browser retry must capture once"
        repo = PostgresFinancialReportingRepository(connection, runtime.tenant)
        report = repo.get_snapshot(captured[0]["id"], actor=actor)
        oracle = financial_snapshot_oracle()
        assert report["effect_count"] == oracle["effect_count"] and report["line_count"] == oracle["line_count"]
        assert str(report["balance_sheet"]["assets_minor"]) == oracle["assets_minor"]
        assert str(report["balance_sheet"]["accumulated_unclosed_result_minor"]) == oracle["result_minor"]
        assert str(report["income_statement"]["income_minor"]) == oracle["income_minor"]
        assert str(report["cash_movements"]["closing_minor"]) == oracle["cash_minor"]
        native = connection.execute("SELECT id FROM reconforge.finance_posting_effects WHERE tenant_id=%s ORDER BY id COLLATE \"C\"",
                                    (runtime.tenant,)).fetchall()
        members = connection.execute("SELECT effect_id FROM reconforge.financial_report_members WHERE tenant_id=%s AND capture_id=%s ORDER BY ordinal",
                                     (runtime.tenant, report["id"])).fetchall()
        assert [row["id"] for row in native] == [row["effect_id"] for row in members]
        assert len(native) == len(AMOUNTS), "Report capture must not add financial effects"
        return {"snapshot_id": report["id"], "report_digest": report["report_digest"],
                "evidence_digest": report["evidence_digest"], "oracle": oracle}
