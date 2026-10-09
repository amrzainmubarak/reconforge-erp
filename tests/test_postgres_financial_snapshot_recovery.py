"""Actual concurrent commits, late evidence failure and immutable report recovery."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

import pytest

from reconforge.domain.finance_posting import canonical_json, digest_payload
from reconforge.domain.financial_reporting_stream import EVIDENCE_CHAIN_SEED
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
from reconforge.infrastructure.postgres_financial_reporting_snapshot_schema import DOWNGRADE_SQL
from reconforge.infrastructure.postgres_financial_reporting_snapshots import PostgresFinancialReportSnapshots
from reconforge.utils.time import utc_now_text
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
    empty = capture(rt, mapping, "empty-reviewed-source")
    assert empty["currency_policy"] is None and empty["effect_count"] == empty["line_count"] == 0
    assert empty["trial_balance"]["accounts"] == [] and empty["balance_sheet"]["assets_minor"] == 0
    with rt.actor("poster") as (connection, _, actor):
        empty_page = PostgresFinancialReportingRepository(connection, rt.tenant).snapshot_evidence(
            empty["id"], expected_digest=empty["report_digest"], actor=actor,
        )
        assert empty_page["items"] == [] and empty_page["next_after"] is None
        assert empty_page["previous_digest"] == empty["evidence_digest"]
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


def test_capture_birth_seal_refuses_nested_temp_trigger_extension_before_summary(snapshot_runtime: ReceiptRuntime) -> None:
    import psycopg
    from psycopg import sql

    rt = snapshot_runtime
    mapping = map_cycle(rt)
    with rt.actor("maker") as (connection, _, actor):
        entry = PostgresFinanceCoreRepository(connection, rt.tenant).create_entry(
            entry_number="AFTER-CAPTURE", organization_code="ORG", entity_code="ENTITY", period_id="period",
            journal_code="STOCK", posting_date="2026-10-09", description="Real source published after report birth",
            lines=[{"account_code": "CASH", "debit": "1.23", "credit": "0"}, {"account_code": "REVENUE", "debit": "0", "credit": "1.23"}],
            workspace="work", actor_label=actor.username,
        )
    with rt.actor("checker") as (connection, _, actor):
        PostgresFinanceCoreRepository(connection, rt.tenant).validate_entry(entry["id"], reason="Independent source review", actor_label=actor.username)
        seal = PostgresFinancePostingRepository(connection, rt.tenant).preview(entry["id"], actor=actor)["current_content_digest"]
    # Capture and posting use distinct identities. Authentication updates their
    # own persisted row, so a second connection must not reauthenticate the
    # reader whose report transaction is deliberately still open.
    with rt.actor("checker") as (connection, _, actor):
        assert connection.execute("SELECT has_column_privilege(current_user,'reconforge.financial_report_captures','membership_sealed','UPDATE')").fetchone()[0]
        assert not connection.execute("SELECT has_column_privilege(current_user,'reconforge.financial_report_captures','source_snapshot','UPDATE')").fetchone()[0]
        request = {"actor_id": actor.user_id, "map_id": mapping["id"], "period_id": "period", "as_of_date": "2026-10-31"}
        with pytest.raises(psycopg.errors.CheckViolation, match="Sealed report membership"), connection.transaction():
            connection.execute("""INSERT INTO reconforge.financial_report_captures(tenant_id,id,workspace_id,organization_id,legal_entity_id,map_id,period_id,as_of_date,actor_id,command_id,request_digest,request_json,source_snapshot,created_at)
                VALUES(%s,'RAW-PREFINAL','work','org','entity',%s,'period','2026-10-31',%s,'raw-prefinal',%s,%s::jsonb,'',%s)""",
                (rt.tenant, mapping["id"], actor.user_id, digest_payload(request), canonical_json(request), utc_now_text()))
            row = connection.execute("SELECT membership_sealed FROM reconforge.financial_report_captures WHERE tenant_id=%s AND id='RAW-PREFINAL'", (rt.tenant,)).fetchone()
            assert row[0] is True
            assert connection.execute("SELECT count(*) FROM reconforge.financial_report_snapshots WHERE tenant_id=%s", (rt.tenant,)).fetchone()[0] == 0
            # A real independently reviewed posting commits after the source
            # cursor ended. The application role's TEMP capability stays enabled.
            with rt.actor("poster") as (posting_connection, _, poster):
                PostgresFinancePostingRepository(posting_connection, rt.tenant).post(
                    entry["id"], command_id="AFTER-CAPTURE-POST", expected_validation_digest=seal,
                    reason="Independent publication after capture source selection", actor=poster,
                )
            connection.execute("CREATE TEMP TABLE capture_depth_probe(value integer)")
            connection.execute("""CREATE FUNCTION pg_temp.capture_depth_probe() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $probe$
                BEGIN
                IF pg_trigger_depth()<>1 THEN RAISE EXCEPTION 'fixture trigger depth differs'; END IF;
                INSERT INTO reconforge.financial_report_members(tenant_id,capture_id,ordinal,effect_id,validation_digest,previous_digest,chain_digest)
                SELECT tenant_id,TG_ARGV[1],1,id,validation_digest,TG_ARGV[2],reconforge.irp_digest(jsonb_build_array(TG_ARGV[2],1,id,validation_digest))
                FROM reconforge.finance_posting_effects WHERE tenant_id=TG_ARGV[0];
                RETURN NEW; END $probe$""")
            connection.execute(sql.SQL("CREATE TRIGGER capture_depth_probe BEFORE INSERT ON capture_depth_probe FOR EACH ROW EXECUTE FUNCTION pg_temp.capture_depth_probe({},{},{})")
                               .format(sql.Literal(rt.tenant), sql.Literal("RAW-PREFINAL"), sql.Literal(EVIDENCE_CHAIN_SEED)))
            connection.execute("INSERT INTO capture_depth_probe VALUES(1)")
        assert connection.execute("SELECT count(*) FROM reconforge.financial_report_captures WHERE tenant_id=%s", (rt.tenant,)).fetchone()[0] == 0
    retained = capture(rt, mapping)
    assert retained["effect_count"] == 1 and retained["balance_sheet"]["assets_minor"] == 123
    with rt.actor("poster") as (connection, _, _actor):
        for statement in ("UPDATE reconforge.financial_report_captures SET membership_sealed=false WHERE tenant_id=%s",
                          "UPDATE reconforge.financial_report_captures SET membership_sealed=true WHERE tenant_id=%s"):
            with pytest.raises(psycopg.errors.CheckViolation, match="provenance"), connection.transaction():
                connection.execute(statement, (rt.tenant,))
