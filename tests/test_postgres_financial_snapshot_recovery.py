"""Actual concurrent commits, late evidence failure and immutable report recovery."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

import pytest

from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
from reconforge.infrastructure.postgres_financial_reporting_snapshot_schema import DOWNGRADE_SQL
from reconforge.infrastructure.postgres_financial_reporting_snapshots import PostgresFinancialReportSnapshots
from tests.test_postgres_financial_reporting import manual, map_cycle, receipt_database, reporting_runtime
from tests.test_postgres_financial_reporting_snapshots import capture, snapshot_runtime
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

__all__ = ["receipt_database", "reporting_runtime", "snapshot_runtime"]


def test_inflight_backdated_native_post_cannot_change_captured_source_or_later_pages(snapshot_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    rt = snapshot_runtime
    mapping = map_cycle(rt)
    manual(rt, "ORIGINAL", "CASH", "REVENUE", 100, "2026-10-09")
    with rt.actor("maker") as (connection, _, actor):
        entry = PostgresFinanceCoreRepository(connection, rt.tenant).create_entry(
            entry_number="CONCURRENT-BACKDATE", organization_code="ORG", entity_code="ENTITY", period_id="period",
            journal_code="STOCK", posting_date="2026-10-08", description="Actual concurrent backdated native source",
            lines=[{"account_code": "CASH", "debit": "2.00", "credit": "0"}, {"account_code": "REVENUE", "debit": "0", "credit": "2.00"}],
            workspace="work", actor_label=actor.username,
        )
    with rt.actor("checker") as (connection, _, actor):
        PostgresFinanceCoreRepository(connection, rt.tenant).validate_entry(entry["id"], reason="Independent concurrent review", actor_label=actor.username)
        seal = PostgresFinancePostingRepository(connection, rt.tenant).preview(entry["id"], actor=actor)["current_content_digest"]
    captured, published = Event(), Event()
    original = PostgresFinancialReportSnapshots._capture
    once = False

    def checkpoint(owner: PostgresFinancialReportSnapshots, identifier: str, actor: Any) -> dict[str, Any]:
        nonlocal once
        value = original(owner, identifier, actor)
        if not once:
            once = True
            captured.set()
            assert published.wait(30), "concurrent native posting did not finish"
        return value

    def native_post() -> None:
        assert captured.wait(30), "report capture checkpoint did not finish"
        # Existing native manual posting compatibility allows its independent
        # reviewer to publish. The new opening path still requires three people.
        with rt.actor("checker") as (connection, _, actor):
            PostgresFinancePostingRepository(connection, rt.tenant).post(entry["id"], command_id="CONCURRENT-POST",
                expected_validation_digest=seal, reason="Actual commit during captured report fold", actor=actor)
        published.set()

    monkeypatch.setattr(PostgresFinancialReportSnapshots, "_capture", checkpoint)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(native_post)
        result = capture(rt, mapping)
        future.result(timeout=30)
    assert result["effect_count"] == 1 and result["balance_sheet"]["assets_minor"] == 100
    with rt.actor("poster") as (connection, _, actor):
        page = PostgresFinancialReportingRepository(connection, rt.tenant).snapshot_evidence(result["id"], expected_digest=result["report_digest"], actor=actor)
        assert page["effect_count"] == 1 and len(page["items"]) == 1 and page["next_after"] is None
    later = capture(rt, mapping, "after-concurrent-commit")
    assert later["effect_count"] == 2 and later["balance_sheet"]["assets_minor"] == 300
    assert capture(rt, mapping) == result
    import psycopg
    with psycopg.connect(rt.admin_dsn) as connection, pytest.raises(psycopg.errors.RaiseException, match="forward recovery"), connection.transaction():
        connection.execute(DOWNGRADE_SQL)
    assert capture(rt, mapping) == result


def test_late_audit_failure_rolls_back_capture_membership_and_exact_command_can_recover(snapshot_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    rt = snapshot_runtime
    mapping = map_cycle(rt)
    manual(rt, "RECOVERY", "CASH", "REVENUE", 101, "2026-10-09")
    with rt.actor("poster") as (connection, _, actor):
        repo = PostgresFinancialReportingRepository(connection, rt.tenant)
        tables = ("financial_report_captures", "financial_report_members", "financial_report_snapshots", "domain_audit_events", "outbox_events")

        def counts() -> list[int]:
            from psycopg import sql
            return [connection.execute(sql.SQL("SELECT count(*) FROM reconforge.{} WHERE tenant_id=%s").format(sql.Identifier(table)), (rt.tenant,)).fetchone()[0] for table in tables]

        before = counts()
        original = repo._event

        def fail_after_event(*args: Any, **kwargs: Any) -> Any:
            original(*args, **kwargs)
            raise RuntimeError("synthetic failure after report audit and outbox")

        monkeypatch.setattr(repo, "_event", fail_after_event)
        arguments = {"map_id": mapping["id"], "period_id": "period", "as_of_date": "2026-10-31", "organization_code": "ORG", "entity_code": "ENTITY", "command_id": "RECOVER-EXACT", "actor": actor}
        with pytest.raises(RuntimeError, match="after report audit"):
            repo.create_snapshot(**arguments)
        assert counts() == before
        monkeypatch.setattr(repo, "_event", original)
        result = repo.create_snapshot(**arguments)
        assert result["effect_count"] == 1 and result["balance_sheet"]["assets_minor"] == 101
        assert repo.create_snapshot(**arguments) == result
        assert counts() == [value + 1 for value in before]
