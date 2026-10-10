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
from tests.test_postgres_finance_scope import (
    finance_database,
    isolated_postgres_migration_dsn,
)
from tests.test_postgres_inventory_receipt_posting import (
    ReceiptRuntime,
    create_receipt_runtime,
    pytestmark,
    receipt_database,
)

__all__ = ["finance_database", "isolated_postgres_migration_dsn", "pytestmark", "receipt_database"]


def seed_asset_masters(runtime: ReceiptRuntime) -> ReceiptRuntime:
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
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
    import psycopg
    runtime = asset_runtime
    first = acquire(runtime)
    with runtime.actor("maker") as (connection, _, actor), pytest.raises(FinancePostingError, match="another"):
        PostgresFixedAssetsRepository(connection, runtime.tenant).acquire(replace(acquisition(), cost_minor=10102), command_id="acquire-MACHINE-1", actor=actor)
    finish(runtime, first)
    with psycopg.connect(runtime.admin_dsn) as connection:
        connection.execute("UPDATE reconforge.fiscal_periods SET status='Closed' WHERE tenant_id=%s AND id='nov'", (runtime.tenant,))
    with pytest.raises(Exception, match="Open|open"):
        operation(runtime, first["asset_id"], kind="depreciate", date="2026-11-01", period="nov", month="2026-10")


def test_pending_asset_protects_all_six_mapped_accounts_period_and_entity(
    asset_runtime: ReceiptRuntime,
) -> None:
    import psycopg

    runtime = asset_runtime
    boundary = PostgresTenantBoundary(runtime.factory)
    with boundary.transaction(runtime.tenant) as connection:
        connection.execute(
            "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,'EUR','Euro',2)",
            (runtime.tenant,),
        )
    plan = acquire(runtime)
    # Only FIXED/CASH appear in the acquisition lines. The other four mappings
    # still belong to the retained lifecycle and cannot be reclassified.
    for account in ("FIXED", "ACCUM", "DEPRECIATION", "CASH", "GAIN", "LOSS"):
        with pytest.raises(psycopg.errors.CheckViolation, match="retained financial classifications"), boundary.transaction(runtime.tenant, workspace_id="work", organization_id="org") as connection:
            connection.execute(
                "UPDATE reconforge.finance_accounts SET account_type='Liability' WHERE tenant_id=%s AND account_code=%s",
                (runtime.tenant, account),
            )
    with pytest.raises(psycopg.errors.CheckViolation, match="open original period"), boundary.transaction(runtime.tenant) as connection:
        connection.execute(
            "UPDATE reconforge.fiscal_periods SET status='Closed' WHERE tenant_id=%s AND id='period'",
            (runtime.tenant,),
        )
    with pytest.raises(psycopg.errors.RaiseException, match="functional currency is immutable"), boundary.transaction(runtime.tenant) as connection:
        connection.execute(
            "UPDATE reconforge.legal_entities SET currency_code='EUR' WHERE tenant_id=%s AND id='entity'",
            (runtime.tenant,),
        )
    finish(runtime, plan)
    assert balances(runtime) == {"FIXED": 10101, "CASH": -10101}


def test_legacy_master_maintenance_without_asset_select_privileges(finance_database: Any) -> None:
    # This role received grants at revision 0094, before asset tables existed.
    # Preserve those real legacy ACLs rather than granting owner dependencies.
    db = finance_database
    with db["boundary"].transaction("finance_scope") as connection:
        flags = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        assert tuple(flags) == (False, False)
        for table in ("fixed_assets", "fixed_asset_plans", "fixed_asset_reviews", "fixed_asset_links", "fixed_asset_commands"):
            assert connection.execute(
                "SELECT has_table_privilege(current_user,%s,'SELECT')", ("reconforge." + table,),
            ).fetchone()[0] is False
        assert connection.execute(
            "SELECT count(*) FROM reconforge.finance_entries WHERE tenant_id='finance_scope' AND upper(left(entry_number,4))='FA1-'",
        ).fetchone()[0] == 0
        for statement in (
            "UPDATE reconforge.legal_entities SET name='Maintained entity' WHERE tenant_id='finance_scope' AND id='entity_a1'",
            "UPDATE reconforge.finance_accounts SET name='Maintained account' WHERE tenant_id='finance_scope' AND account_code='A_CASH'",
            "UPDATE reconforge.finance_journals SET name='Maintained journal' WHERE tenant_id='finance_scope' AND journal_code='J_A'",
            "UPDATE reconforge.fiscal_periods SET name='Maintained period' WHERE tenant_id='finance_scope' AND id='period'",
        ):
            assert connection.execute(statement).rowcount == 1
    # The transaction must commit all deferred OLD/NEW owner guards successfully.
    with db["boundary"].transaction("finance_scope") as connection:
        assert connection.execute(
            "SELECT name FROM reconforge.fiscal_periods WHERE tenant_id='finance_scope' AND id='period'",
        ).fetchone()[0] == "Maintained period"


def test_current_amount_policy_is_applied_before_acquisition_and_retained_ack(asset_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal

    import reconforge.infrastructure.postgres_operational_finance as authority
    from reconforge.auth.policy import evaluate_principal_access
    runtime = asset_runtime
    ceiling = Decimal("100.00")
    observed: list[Decimal | None] = []

    def governed_policy(principal: Any, **context: Any) -> Any:
        observed.append(context.get("amount"))
        return evaluate_principal_access(principal, maximum_amount=ceiling, **context)

    monkeypatch.setattr(authority, "evaluate_principal_access", governed_policy)
    with runtime.actor("maker") as (connection, _, actor):
        repository = PostgresFixedAssetsRepository(connection, runtime.tenant)
        with pytest.raises(FinancePostingError, match="authorization"):
            repository.acquire(acquisition(), command_id="amount-acquire", actor=actor)
        assert connection.execute("SELECT count(*) n FROM reconforge.fixed_assets WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_entries WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
        ceiling = Decimal("200.00")
        plan = repository.acquire(acquisition(), command_id="amount-acquire", actor=actor)
        ceiling = Decimal("100.00")
        with pytest.raises(FinancePostingError, match="authorization"):
            repository.acquire(acquisition(), command_id="amount-acquire", actor=actor)
        ceiling = Decimal("200.00")
        assert repository.acquire(acquisition(), command_id="amount-acquire", actor=actor) == plan
    assert observed and set(observed) == {Decimal("101.01")}


def test_disposal_policy_uses_full_turnover_on_prepare_and_replay(asset_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal

    import reconforge.infrastructure.postgres_operational_finance as authority
    from reconforge.auth.policy import evaluate_principal_access
    runtime = asset_runtime
    initial = finish(runtime, acquire(runtime, replace(acquisition(), cost_minor=101, salvage_minor=0, useful_life_months=1)))
    finish(runtime, operation(runtime, initial["asset_id"], kind="depreciate", date="2026-11-01", period="nov", month="2026-10"))
    ceiling = Decimal("100.00")
    observed: list[Decimal | None] = []

    def governed_policy(principal: Any, **context: Any) -> Any:
        observed.append(context.get("amount"))
        return evaluate_principal_access(principal, maximum_amount=ceiling, **context)

    monkeypatch.setattr(authority, "evaluate_principal_access", governed_policy)
    with runtime.actor("maker") as (connection, _, actor):
        repository = PostgresFixedAssetsRepository(connection, runtime.tenant)
        args = dict(kind="dispose", period_id="nov", posting_date="2026-11-02", reason="Governed high proceeds zero book disposal", command_id="amount-disposal", actor=actor, proceeds_minor=20000)
        with pytest.raises(FinancePostingError, match="authorization"):
            repository.prepare(initial["asset_id"], **args)
        assert connection.execute("SELECT count(*) n FROM reconforge.fixed_asset_plans WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 2
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_entries WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 2
        ceiling = Decimal("300.00")
        plan = repository.prepare(initial["asset_id"], **args)
        assert plan["amount_minor"] == 0
        ceiling = Decimal("100.00")
        with pytest.raises(FinancePostingError, match="authorization"):
            repository.prepare(initial["asset_id"], **args)
        ceiling = Decimal("300.00")
        assert repository.prepare(initial["asset_id"], **args) == plan
    assert observed and set(observed) == {Decimal("201.01")}


def test_unrelated_worker_audit_and_outbox_delivery_need_no_asset_table_privileges(
    asset_runtime: ReceiptRuntime,
) -> None:
    """Commit under a real restricted role with no access to any asset owner."""
    from contextlib import contextmanager
    from uuid import uuid4

    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
    from reconforge.infrastructure.postgres_outbox import PostgresOutboxRepository

    runtime = asset_runtime
    role = "fa_unrelated_worker_" + uuid4().hex[:12]
    app_user = psycopg.conninfo.conninfo_to_dict(runtime.factory.settings.dsn)["user"]
    event_id = "unrelated-" + uuid4().hex
    owned_event_id = "reserved-" + uuid4().hex
    missing_plan = "FA1-" + uuid4().hex
    boundary = PostgresTenantBoundary(runtime.factory)

    @contextmanager
    def worker() -> Any:
        with boundary.transaction(
            runtime.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity",
        ) as connection:
            connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            yield connection

    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        admin.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(role), sql.Identifier(app_user)))
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(role)))
        for privileges, tables in (
            ("SELECT", "tenants"),
            ("SELECT,INSERT,UPDATE", "domain_audit_ledger_state"),
            ("SELECT,INSERT", "domain_audit_events,outbox_events,outbox_delivery_evidence"),
        ):
            admin.execute(sql.SQL("GRANT {} ON {} TO {}").format(
                sql.SQL(privileges),
                sql.SQL(",").join(sql.Identifier("reconforge", name) for name in tables.split(",")),
                sql.Identifier(role),
            ))
        admin.execute(sql.SQL("""GRANT UPDATE(status,attempt_count,available_at,claimed_at,
            claimed_by,published_at,last_error,dead_lettered_at,lease_generation)
            ON reconforge.outbox_events TO {}""").format(sql.Identifier(role)))
    try:
        with worker() as connection:
            flags = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            assert dict(flags) == {"rolsuper": False, "rolbypassrls": False}
            for table in ("fixed_assets", "fixed_asset_plans", "fixed_asset_reviews", "fixed_asset_links", "fixed_asset_commands"):
                assert connection.execute(
                    "SELECT has_table_privilege(current_user,%s,'SELECT') allowed", ("reconforge." + table,),
                ).fetchone()["allowed"] is False
            audit = PostgresAuditEventRepository(connection, runtime.tenant).append(
                actor_label="restricted-reconciliation-worker", object_type="reconciliation_run",
                object_id="unrelated-run", action="reconciliation_completed", metadata={"synthetic": True},
            )
            connection.execute("""INSERT INTO reconforge.outbox_events
                (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
                VALUES(%s,%s,'reconciliation_completed','reconciliation_run','unrelated-run',%s::jsonb)""",
                (runtime.tenant, event_id, '{"audit_event_id":"' + audit.id + '"}'))
        # Both claim and ACK commit their deferred owner triggers as the worker.
        with worker() as connection:
            claimed = PostgresOutboxRepository(connection).claim_pending(
                tenant_id=runtime.tenant, worker_id="restricted-worker", limit=10, lease_seconds=60,
            )
            assert [event.id for event in claimed] == [event_id]
        with worker() as connection:
            PostgresOutboxRepository(connection).mark_published(
                tenant_id=runtime.tenant, event_id=event_id, worker_id="restricted-worker",
                lease_generation=claimed[0].lease_generation,
            )
        with worker() as connection:
            assert connection.execute(
                "SELECT status FROM reconforge.outbox_events WHERE tenant_id=%s AND event_id=%s",
                (runtime.tenant, event_id),
            ).fetchone()["status"] == "Published"
            delivery_rows = connection.execute(
                "SELECT action FROM reconforge.outbox_delivery_evidence WHERE tenant_id=%s AND event_id=%s ORDER BY occurred_at",
                (runtime.tenant, event_id),
            ).fetchall()
            assert [row["action"] for row in delivery_rows] == ["claimed", "published"]
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="fixed_asset_plans"), worker() as connection:
            connection.execute("""INSERT INTO reconforge.outbox_events
                (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
                VALUES(%s,%s,'fixed_asset_prepared','operational_finance',%s,'{}'::jsonb)""",
                (runtime.tenant, owned_event_id, missing_plan))
        # The same reserved event fails its owner equation with normal module access.
        with pytest.raises(psycopg.errors.CheckViolation, match="retained asset owner"), runtime.actor("maker") as (connection, _, _):
            connection.execute("""INSERT INTO reconforge.outbox_events
                (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
                VALUES(%s,%s,'fixed_asset_prepared','operational_finance',%s,'{}'::jsonb)""",
                (runtime.tenant, owned_event_id, missing_plan))
    finally:
        with psycopg.connect(runtime.admin_dsn) as admin:
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
