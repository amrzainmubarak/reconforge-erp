"""Independent residual/GL oracle and governed unposted collection release."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

from reconforge.domain.commercial_collections import CommercialCollectionPreparation
from reconforge.domain.finance_posting import FinancePostingError, digest_payload
from reconforge.infrastructure.postgres_commercial_collections import PostgresCommercialCollectionsRepository
from tests.test_postgres_commercial_collections import complete, invoiced, phase, prepare
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database
from tests.test_postgres_stock_commerce import repository
from tests.test_postgres_stock_sales import create_stock_runtime

_ = receipt_database


def financial_snapshot(connection: Any, tenant: str) -> str:
    from psycopg import sql

    tables = connection.execute("""SELECT c.table_name FROM information_schema.columns c
        JOIN information_schema.tables t ON(t.table_schema,t.table_name)=(c.table_schema,c.table_name)
        WHERE c.table_schema='reconforge' AND c.column_name='tenant_id' AND t.table_type='BASE TABLE'
        AND c.table_name ~ '^(finance_|ar_|inventory_|stock_)' ORDER BY c.table_name""").fetchall()
    return digest_payload({row["table_name"]: [entry["value"] for entry in connection.execute(
        sql.SQL("SELECT to_jsonb(r) value FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text")
        .format(sql.Identifier(row["table_name"])), (tenant,)).fetchall()] for row in tables})


def cancel(runtime: ReceiptRuntime, plan: dict[str, Any], who: str, command: str = "cancel") -> dict[str, Any]:
    with runtime.actor(who) as (connection, _, actor):
        return PostgresCommercialCollectionsRepository(connection, runtime.tenant).cancel(plan["id"],
            expected_plan_digest=plan["plan_digest"], command_id=command, reason="Release retained receipt collision", actor=actor)


@pytest.mark.parametrize("reviewed", [False, True])
def test_cancel_releases_only_claim_preserves_history_and_replacement_settles_independent_oracle(
    receipt_database: tuple[str, str], reviewed: bool,
) -> None:
    runtime = create_stock_runtime(receipt_database)
    order, invoice = invoiced(runtime)
    prepared = prepare(runtime, invoice, 10000)
    plan = phase(runtime, prepared, "review", "checker", "review") if reviewed else prepared
    with runtime.actor("maker") as (connection, _, _actor):
        before = financial_snapshot(connection, runtime.tenant)
    for who in (("maker", "checker") if reviewed else ("maker",)):
        with pytest.raises(FinancePostingError, match="independent"):
            cancel(runtime, plan, who)
    who = "poster" if reviewed else "checker"
    released = cancel(runtime, plan, who)
    assert released["status"] == "Cancelled" and released["phase"] == 3
    assert released["cancelled_actor_id"] == who and released["posting_effect_id"] is None and released["receipt_id"] is None
    assert cancel(runtime, plan, who) == released
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCommercialCollectionsRepository(connection, runtime.tenant)
        assert financial_snapshot(connection, runtime.tenant) == before
        assert owner.get(plan["id"], actor=actor) == released
        request = CommercialCollectionPreparation(**{key: prepared[key] for key in CommercialCollectionPreparation.__dataclass_fields__})
        assert owner.prepare(request, command_id="prepare-FIRST", actor=actor) == prepared
        tranche = repository(connection, runtime).get(order["id"], actor=actor)["lines"][0]["tranches"][0]
        assert tranche["pending_collection"] is None
        assert tranche["collected_minor"] == "0" and tranche["outstanding_minor"] == "45000"
        replacement = owner.prepare(replace(request, amount_minor=45000), command_id="replacement", actor=actor)
        assert replacement["receipt_number"] == prepared["receipt_number"] and replacement["id"] != prepared["id"]
    if reviewed:
        assert phase(runtime, prepared, "review", "checker", "review") == plan
    with pytest.raises(FinancePostingError):
        phase(runtime, released, "post", "poster", "post-cancelled")
    complete(runtime, replacement, "replacement")
    with runtime.actor("maker") as (connection, _, actor):
        assert PostgresCommercialCollectionsRepository(connection, runtime.tenant).get(plan["id"], actor=actor) == released
        assert connection.execute("SELECT count(*) n FROM reconforge.ar_receipts WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.commercial_collection_cancellations WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT sum(amount_minor) n FROM reconforge.ar_receipt_allocations WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 45000
        balances = {row["account_code"]: int(row["balance"]) for row in connection.execute("""SELECT a.account_code,sum(l.debit_minor-l.credit_minor) balance
            FROM reconforge.finance_posting_effects f JOIN reconforge.finance_entry_lines l ON l.tenant_id=f.tenant_id AND l.entry_id=f.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
            WHERE f.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()}
        # Ten units cost12000, frozen unit price4500: cancellation affects none
        # of FIFO, revenue, cash or AR; only one subsequent actual receipt does.
        assert balances["CASH"] == 45000 and balances["AR"] == 0
        assert balances["COGS"] == 12000 and balances["REVENUE"] == -45000 and balances["INVENTORY"] == 0
        row = connection.execute("SELECT status,total_minor FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s", (runtime.tenant, invoice)).fetchone()
        assert row["status"] == "Paid" and row["total_minor"] == 45000


def test_cancellation_exact_ack_requires_current_authority_and_bound_actor(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    _, invoice = invoiced(runtime)
    plan = prepare(runtime, invoice, 10000)
    released = cancel(runtime, plan, "checker")
    with runtime.actor("checker") as (connection, _, _actor):
        assert dict(connection.execute("""SELECT relrowsecurity,relforcerowsecurity FROM pg_class
            WHERE oid='reconforge.commercial_collection_cancellations'::regclass""").fetchone()) == {"relrowsecurity": True, "relforcerowsecurity": True}
        for setting in ("app.tenant_id", "app.workspace_id", "app.organization_id", "app.legal_entity_id"):
            with connection.transaction():
                connection.execute("SELECT set_config(%s,'outside',true)", (setting,))
                assert connection.execute("SELECT count(*) n FROM reconforge.commercial_collection_cancellations").fetchone()["n"] == 0
                # Restore the scoped setting before leaving this savepoint.
                value = runtime.tenant if setting == "app.tenant_id" else {"app.workspace_id": "work", "app.organization_id": "org", "app.legal_entity_id": "entity"}[setting]
                connection.execute("SELECT set_config(%s,%s,true)", (setting, value))
    with pytest.raises(FinancePostingError, match="another actor or request"):
        cancel(runtime, plan, "poster")
    with pytest.raises(FinancePostingError, match="authorization denied"), runtime.actor("checker") as (connection, _, actor):
        connection.execute("""UPDATE reconforge.identity_role_permissions SET active=false,lifecycle_version=lifecycle_version+1,
            revoked_at=now(),revoked_by='maker',revocation_reason_code='access_change'
            WHERE tenant_id=%s AND permission_name='sales.approve'""", (runtime.tenant,))
        PostgresCommercialCollectionsRepository(connection, runtime.tenant).cancel(plan["id"],
            expected_plan_digest=plan["plan_digest"], command_id="cancel", reason=released["cancellation_reason"], actor=actor)


def test_cancellation_rejects_stale_digest_posted_plan_and_direct_sql_shortcuts(receipt_database: tuple[str, str]) -> None:
    import psycopg

    runtime = create_stock_runtime(receipt_database)
    _, invoice = invoiced(runtime)
    plan = prepare(runtime, invoice, 10000)
    with pytest.raises(FinancePostingError, match="current unposted"), runtime.actor("checker") as (connection, _, actor):
        PostgresCommercialCollectionsRepository(connection, runtime.tenant).cancel(plan["id"],
            expected_plan_digest="f" * 64, command_id="stale", reason="Stale release", actor=actor)
    with pytest.raises(psycopg.errors.CheckViolation, match="independent evidence"), runtime.actor("maker") as (connection, _, _actor):
        connection.execute("UPDATE reconforge.commercial_collection_plans SET phase=3 WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["id"]))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(psycopg.errors.CheckViolation, match="current independent"), runtime.actor("maker") as (connection, _, _actor):
        connection.execute("""INSERT INTO reconforge.commercial_collection_cancellations
            (tenant_id,plan_id,cancelled_actor_id,reason,audit_event_id,outbox_event_id)
            SELECT tenant_id,id,payload->>'preparer_actor_id','Self release',audit_event_id,outbox_event_id
            FROM reconforge.commercial_collection_plans WHERE tenant_id=%s AND id=%s""", (runtime.tenant, plan["id"]))
    released = cancel(runtime, plan, "checker")
    with pytest.raises(psycopg.errors.CheckViolation, match="immutable"), runtime.actor("checker") as (connection, _, _actor):
        connection.execute("UPDATE reconforge.commercial_collection_cancellations SET reason='Altered' WHERE tenant_id=%s AND plan_id=%s", (runtime.tenant, plan["id"]))
    replacement = prepare(runtime, invoice, 10000, "POSTED")
    posted = complete(runtime, replacement, "POSTED")
    with pytest.raises(FinancePostingError, match="current unposted"):
        cancel(runtime, posted, "checker", "cancel-posted")
    assert cancel(runtime, plan, "checker") == released


def test_concurrent_cancel_lost_ack_has_one_terminal_release(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    _, invoice = invoiced(runtime)
    plan = phase(runtime, prepare(runtime, invoice, 10000), "review", "checker", "review")
    with ThreadPoolExecutor(max_workers=3) as executor:
        responses = list(executor.map(lambda _: cancel(runtime, plan, "poster"), range(3)))
    assert responses[0] == responses[1] == responses[2]
    with runtime.actor("poster") as (connection, _, _actor):
        assert connection.execute("SELECT count(*) n FROM reconforge.commercial_collection_cancellations WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.commercial_collection_commands WHERE tenant_id=%s AND operation='cancel'", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.ar_receipts WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0


def test_cancel_races_post_without_split_cash_or_orphaned_release(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    _, invoice = invoiced(runtime)
    plan = phase(runtime, prepare(runtime, invoice, 10000), "review", "checker", "review")

    def attempt(operation: str) -> str:
        try:
            return (cancel(runtime, plan, "poster") if operation == "cancel" else phase(runtime, plan, "post", "poster", "post-race"))["status"]
        except FinancePostingError as exc:
            assert exc.code in {"collection_state_conflict", "collection_review_invalid"}
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ("cancel", "post")))
    assert results.count("refused") == 1
    with runtime.actor("poster") as (connection, _, actor):
        retained = PostgresCommercialCollectionsRepository(connection, runtime.tenant).get(plan["id"], actor=actor)
        cancellations = connection.execute("SELECT count(*) n FROM reconforge.commercial_collection_cancellations WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"]
        receipts = connection.execute("SELECT count(*) n FROM reconforge.ar_receipts WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"]
        assert (cancellations, receipts) == ((1, 0) if retained["status"] == "Cancelled" else (0, 1))


def test_failure_after_release_before_ack_rolls_back_claim_event_and_command(receipt_database: tuple[str, str], monkeypatch: Any) -> None:
    runtime = create_stock_runtime(receipt_database)
    _, invoice = invoiced(runtime)
    plan = prepare(runtime, invoice, 10000)
    with runtime.actor("checker") as (connection, _, actor):
        owner = PostgresCommercialCollectionsRepository(connection, runtime.tenant)
        before = financial_snapshot(connection, runtime.tenant)
        def lost_ack(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("Synthetic failure before command retention")
        monkeypatch.setattr(owner, "_remember", lost_ack)
        with pytest.raises(RuntimeError, match="Synthetic failure"):
            owner.cancel(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="failed-release", reason="Failure injection", actor=actor)
        assert financial_snapshot(connection, runtime.tenant) == before
        assert owner.get(plan["id"], actor=actor) == plan
        assert connection.execute("SELECT count(*) n FROM reconforge.commercial_collection_cancellations WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) n FROM reconforge.domain_audit_events WHERE tenant_id=%s AND action='commercial_collection_cancelled'", (runtime.tenant,)).fetchone()["n"] == 0
    assert cancel(runtime, plan, "checker")["status"] == "Cancelled"


def test_forward_upgrade_retains_reviewed_history_empty_release_rollback_and_populated_refusal() -> None:
    delegated = receipt_database.__wrapped__()
    isolated = next(delegated)
    try:
        _verify_forward_upgrade(isolated)
    finally:
        with pytest.raises(StopIteration):
            next(delegated)


def _verify_forward_upgrade(database: tuple[str, str]) -> None:
    import psycopg

    from reconforge.infrastructure.postgres_commercial_collections_cancellation_schema import DOWNGRADE_SQL, UPGRADE_SQL

    runtime = create_stock_runtime(database)
    _, invoice = invoiced(runtime)
    prepared = prepare(runtime, invoice, 10000)
    reviewed = phase(runtime, prepared, "review", "checker", "review")
    with runtime.actor("checker") as (connection, _, _actor):
        before = financial_snapshot(connection, runtime.tenant)
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute(DOWNGRADE_SQL)
        assert admin.execute("SELECT to_regclass('reconforge.commercial_collection_cancellations')").fetchone()[0] is None
    with runtime.actor("checker") as (connection, _, actor):
        assert PostgresCommercialCollectionsRepository(connection, runtime.tenant).get(prepared["id"], actor=actor) == reviewed
        assert financial_snapshot(connection, runtime.tenant) == before
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute(UPGRADE_SQL)
        app_user = psycopg.conninfo.conninfo_to_dict(database[1])["user"]
        from psycopg import sql
        admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.commercial_collection_cancellations TO {}")
            .format(sql.Identifier(app_user)))
    assert phase(runtime, prepared, "review", "checker", "review") == reviewed
    cancel(runtime, reviewed, "poster")
    with pytest.raises(psycopg.Error, match="refuses to discard"), psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute(DOWNGRADE_SQL)
    assert cancel(runtime, reviewed, "poster")["status"] == "Cancelled"
