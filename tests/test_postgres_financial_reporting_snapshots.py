"""Configured native reporting beyond the legacy effect budget; no synthetic GL shortcut."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter_ns
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
from reconforge.infrastructure.postgres_financial_reporting_snapshot_schema import (
    install_postgres_financial_reporting_snapshot_schema,
)
from tests.test_postgres_financial_reporting import manual, map_cycle, receipt_database, reporting_runtime
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_operational_finance_api import client_for

__all__ = ["receipt_database", "reporting_runtime"]


@pytest.fixture
def snapshot_runtime(reporting_runtime: ReceiptRuntime) -> ReceiptRuntime:
    import psycopg
    from psycopg import sql
    rt = reporting_runtime
    with psycopg.connect(rt.admin_dsn) as connection:
        install_postgres_financial_reporting_snapshot_schema(connection)
        user = psycopg.conninfo.conninfo_to_dict(rt.factory.settings.dsn)["user"]
        for table in ("financial_report_captures", "financial_report_members", "financial_report_snapshots"):
            connection.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(user)))
    return rt


def capture(rt: ReceiptRuntime, mapping: dict[str, Any], command: str = "snapshot") -> dict[str, Any]:
    with rt.actor("poster") as (connection, _, actor):
        return PostgresFinancialReportingRepository(connection, rt.tenant).create_snapshot(
            map_id=mapping["id"], period_id="period", as_of_date="2026-10-31", organization_code="ORG",
            entity_code="ENTITY", command_id=command, actor=actor,
        )


def native_history(rt: ReceiptRuntime, count: int) -> int:
    prepared: list[tuple[str, int]] = []
    with rt.actor("maker") as (connection, _, actor):
        finance = PostgresFinanceCoreRepository(connection, rt.tenant)
        for ordinal in range(count):
            amount = (ordinal * 37 % 997) + 1
            entry = finance.create_entry(entry_number=f"BULK-{ordinal:06d}", organization_code="ORG", entity_code="ENTITY",
                                         period_id="period", journal_code="STOCK", posting_date="2026-10-09", description="Deterministic native business history",
                                         lines=[{"account_code": "CASH", "debit": f"{amount // 100}.{amount % 100:02d}", "credit": "0"},
                                                {"account_code": "REVENUE", "debit": "0", "credit": f"{amount // 100}.{amount % 100:02d}"}],
                                         workspace="work", actor_label=actor.username)
            prepared.append((entry["id"], amount))
    seals: list[tuple[str, str]] = []
    with rt.actor("checker") as (connection, _, actor):
        finance, posting = PostgresFinanceCoreRepository(connection, rt.tenant), PostgresFinancePostingRepository(connection, rt.tenant)
        for identifier, _ in prepared:
            finance.validate_entry(identifier, reason="Independent synthetic source verification", actor_label=actor.username)
            seals.append((identifier, posting.preview(identifier, actor=actor)["current_content_digest"]))
    with rt.actor("poster") as (connection, _, actor):
        posting = PostgresFinancePostingRepository(connection, rt.tenant)
        for ordinal, (identifier, seal) in enumerate(seals):
            posting.post(identifier, command_id=f"BULK-POST-{ordinal}", expected_validation_digest=seal, reason="Independent publication", actor=actor)
    return sum(amount for _, amount in prepared)


def test_native_snapshot_exceeds_1000_effects_exact_oracle_and_pages_every_contribution(snapshot_runtime: ReceiptRuntime, record_property: Any) -> None:
    rt = snapshot_runtime
    mapping = map_cycle(rt)
    history_started = perf_counter_ns()
    expected = native_history(rt, 1_005)
    record_property("native_prepare_review_post_ns", perf_counter_ns() - history_started)
    with rt.actor("poster") as (connection, _, actor):
        with pytest.raises(FinancePostingError) as legacy:
            PostgresFinancialReportingRepository(connection, rt.tenant).report(map_id=mapping["id"], period_id="period", as_of_date="2026-10-31", organization_code="ORG", entity_code="ENTITY", actor=actor)
        assert legacy.value.code == "posting_balance_limit"
    capture_started = perf_counter_ns()
    result = capture(rt, mapping)
    record_property("native_captured_report_ns", perf_counter_ns() - capture_started)
    assert result["effect_count"] == 1_005 and result["line_count"] == 2_010
    assert result["balance_sheet"]["assets_minor"] == result["income_statement"]["result_minor"] == expected
    assert capture(rt, mapping) == result
    after, seen, total, previous = 0, set(), 0, None
    with rt.actor("poster") as (connection, _, actor):
        repo = PostgresFinancialReportingRepository(connection, rt.tenant)
        while True:
            page = repo.snapshot_evidence(result["id"], expected_digest=result["report_digest"], actor=actor, after=after, limit=200)
            if previous is not None:
                assert page["previous_digest"] == previous
            for item in page["items"]:
                assert item["effect_id"] not in seen
                seen.add(item["effect_id"])
                total += sum(line["debit_minor"] for line in item["effect"]["snapshot"]["lines"])
            previous = page["items"][-1]["chain_digest"]
            if page["next_after"] is None:
                break
            after = page["next_after"]
    assert len(seen) == 1_005 and total == expected and previous == result["evidence_digest"]
    # Compare the existing verified per-effect loader with the shared batched
    # verifier on exactly the same immutable native set. Alternating order
    # records cache-sensitive samples rather than inventing an ERP TPS result.
    class MeasuredConnection:
        def __init__(self, connection: Any) -> None:
            self.connection, self.queries = connection, 0

        def execute(self, *args: Any, **kwargs: Any) -> Any:
            self.queries += 1
            return self.connection.execute(*args, **kwargs)

        def __getattr__(self, key: str) -> Any:
            return getattr(self.connection, key)

    with rt.actor("poster") as (connection, _, actor):
        identifiers = [row[0] for row in connection.execute("SELECT effect_id FROM reconforge.financial_report_members WHERE tenant_id=%s AND capture_id=%s ORDER BY ordinal", (rt.tenant, result["id"]))]
        measured = MeasuredConnection(connection)
        posting = PostgresFinancePostingRepository(measured, rt.tenant)
        expected_digest: str | None = None
        for repetition in range(3):
            for path in (("baseline", "optimized") if repetition % 2 == 0 else ("optimized", "baseline")):
                measured.queries = 0
                started, amount, chain = perf_counter_ns(), 0, ""
                values = (posting._get_effect(identifier) for identifier in identifiers) if path == "baseline" else posting.iter_verified_posting_effects(effect_ids=iter(identifiers), actor=actor, batch_size=100)
                for value in values:
                    amount += sum(line["debit_minor"] for line in value["snapshot"]["lines"])
                    chain = digest_payload([chain, value["id"], value["validation_digest"]])
                elapsed = perf_counter_ns() - started
                assert amount == expected
                if expected_digest is None:
                    expected_digest = chain
                assert chain == expected_digest
                record_property(f"{path}_{repetition}_ns", elapsed)
                record_property(f"{path}_{repetition}_application_queries", measured.queries)
        record_property("native_effect_count", len(identifiers))
        record_property("native_exact_oracle_minor", expected)
        record_property("native_verified_input_digest", expected_digest)


def test_snapshot_retains_capture_after_backdated_post_replay_conflict_and_authorized_http(snapshot_runtime: ReceiptRuntime, receipt_database: tuple[str, str], tmp_path: Path) -> None:
    rt = snapshot_runtime
    mapping = map_cycle(rt)
    manual(rt, "FIRST", "CASH", "REVENUE", 9007199254740993, "2026-10-09")
    initial = capture(rt, mapping)
    manual(rt, "BACKDATE", "CASH", "REVENUE", 101, "2026-10-08")
    assert capture(rt, mapping) == initial
    latest = capture(rt, mapping, "next-snapshot")
    assert latest["effect_count"] == 2
    assert latest["balance_sheet"]["assets_minor"] == 9007199254741094
    with client_for(rt, receipt_database, tmp_path, "poster", step_up=False) as (client, headers):
        response = client.get(f"/api/v1/financial-reporting/snapshots/{initial['id']}", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["snapshot"]["balance_sheet"]["assets_minor"] == "9007199254740993"
        bad = client.get(f"/api/v1/financial-reporting/snapshots/{initial['id']}/evidence", headers=headers, params={"expected_digest": latest["report_digest"]})
        assert bad.status_code == 409, bad.text
        headers["X-ReconForge-Legal-Entity"] = "foreign"
        assert client.get(f"/api/v1/financial-reporting/snapshots/{initial['id']}", headers=headers).status_code == 403


def test_snapshot_membership_and_summary_cannot_be_tampered_or_injected_even_direct_sql(snapshot_runtime: ReceiptRuntime) -> None:
    from psycopg.errors import CheckViolation
    rt = snapshot_runtime
    mapping = map_cycle(rt)
    manual(rt, "ONE", "CASH", "REVENUE", 10, "2026-10-09")
    result = capture(rt, mapping)
    with rt.actor("poster") as (connection, _, actor):
        for query in (
            "UPDATE reconforge.financial_report_snapshots SET payload=payload||'{\"effect_count\":0}'::jsonb WHERE tenant_id=%s",
            "DELETE FROM reconforge.financial_report_members WHERE tenant_id=%s",
            "INSERT INTO reconforge.financial_report_members SELECT tenant_id,capture_id,ordinal+1,effect_id,validation_digest,previous_digest,chain_digest FROM reconforge.financial_report_members WHERE tenant_id=%s",
        ):
            with pytest.raises(CheckViolation), connection.transaction():
                connection.execute(query, (rt.tenant,))
        assert PostgresFinancialReportingRepository(connection, rt.tenant).get_snapshot(result["id"], actor=actor) == result
    with PostgresTenantBoundary(rt.factory).transaction(rt.tenant, workspace_id="work", organization_id="org", legal_entity_id="other") as connection:
        assert connection.execute("SELECT count(*) FROM reconforge.financial_report_captures").fetchone()[0] == 0
