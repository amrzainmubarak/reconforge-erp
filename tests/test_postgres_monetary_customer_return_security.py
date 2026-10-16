"""Actual ordinary-role149 SQL, replay, failure and lock-wait authority checks."""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier

import psycopg
import pytest
from psycopg import sql

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.monetary_customer_partial_return_commands import MonetaryPartialReturnPreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_monetary_customer_partial_returns import (
    PostgresMonetaryCustomerPartialReturnsRepository,
)
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.platform.common import current_server_principal, server_principal_context
from tests.customer_partial_return_monetary_posted_oracle import TABLES
from tests.test_postgres_inventory_receipt_posting import receipt_database
from tests.test_postgres_monetary_customer_partial_returns import DAY, SCOPE, _phase, _posted, _return, _source

_ = receipt_database


def _business_digest(runtime):
    result = hashlib.sha256()
    with runtime.actor("maker") as (connection, _, _actor):
        flags = connection.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user").fetchone()
        assert flags is not None and all(type(flags[name]) is bool and not flags[name]
            for name in ("rolsuper", "rolbypassrls", "rolcreatedb", "rolcreaterole", "rolreplication"))
        for name in TABLES:
            if name in {"domain_audit_events", "domain_audit_ledger_state"}:
                continue
            rows = connection.execute(sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text")
                .format(sql.Identifier(name)), (runtime.tenant,)).fetchall()
            assert len(rows) <= 4096
            result.update(name.encode())
            for row in rows:
                result.update(hashlib.sha256(row["original"].encode()).digest())
    return result.hexdigest()


@pytest.mark.parametrize("attack", ["origin-balance", "history-update", "phase-forgery", "fifo-forgery"])
def test_actual_direct_sql_cannot_forge_monetary_native_state(receipt_database, attack):
    runtime, order = _source(receipt_database, foreign=True)
    plan = _return(runtime, order, 4, 0)
    if attack in {"history-update", "fifo-forgery"}:
        plan = _posted(runtime, plan)
    before = _business_digest(runtime)
    expected = psycopg.errors.RaiseException if attack == "fifo-forgery" else psycopg.errors.CheckViolation
    with pytest.raises(expected), runtime.actor("poster") as (connection, _, _actor):
        if attack == "origin-balance":
            connection.execute("""UPDATE reconforge.stock_sales_monetary_origins
                SET ar_balance=jsonb_set(ar_balance,'{transaction_outstanding_minor}','"0"'::jsonb)
                WHERE tenant_id=%s AND stock_order_id=%s""", (runtime.tenant, order["id"]))
        elif attack == "history-update":
            connection.execute("""UPDATE reconforge.customer_partial_return_monetary_history
                SET payload=jsonb_set(payload,'{quantity_scaled}','99'::jsonb) WHERE tenant_id=%s AND partial_plan_id=%s""", (runtime.tenant, plan["id"]))
        elif attack == "phase-forgery":
            connection.execute("UPDATE reconforge.customer_partial_return_monetary_plans SET phase=2 WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["id"]))
        else:
            connection.execute("UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=remaining_quantity_scaled+1 WHERE tenant_id=%s", (runtime.tenant,))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert _business_digest(runtime) == before


@pytest.mark.parametrize("same_command", [False, True], ids=["distinct-conflict", "same-exact-replay"])
def test_actual_concurrent_preparation_has_one_reserved_business_effect(receipt_database, same_command):
    runtime, order = _source(receipt_database, foreign=True)
    ready = Barrier(2)

    def contender(number):
        try:
            with runtime.actor("maker") as (connection, _, actor):
                connection.execute("SET LOCAL lock_timeout='5s'")
                connection.execute("SET LOCAL statement_timeout='10s'")
                ready.wait(timeout=5)
                request = MonetaryPartialReturnPreparation(**SCOPE, organization_code="ORG", entity_code="ENTITY", source_order_id=order["id"],
                    quantity_scaled=6, period_id="period", posting_date=DAY, reason="Exact competing monetary intent", expected_history_version=0)
                return PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant).prepare(request,
                    command_id="concurrent-return" + ("" if same_command else str(number)), actor=actor)
        except FinancePostingError as exc:
            assert exc.code == "monetary_return_state_conflict"
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(contender, (1, 2)))
    if same_command:
        assert outcomes[0] is not None and outcomes[0] == outcomes[1]
    else:
        assert sum(value is not None for value in outcomes) == 1
    with runtime.actor("maker") as (connection, _, _actor):
        assert connection.execute("SELECT count(*) n FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.customer_partial_return_monetary_history WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0


def test_actual_failure_after_first_real_gl_effect_rolls_back_and_exact_retry_succeeds(receipt_database, monkeypatch):
    runtime, order = _source(receipt_database, foreign=True)
    reviewed = _phase(runtime, _return(runtime, order, 4, 0), "review", "checker")
    before = _business_digest(runtime)
    real_post = PostgresFinancePostingRepository.post
    completed = []

    def interrupted(self, *arguments, **keywords):
        result = real_post(self, *arguments, **keywords)
        completed.append(result["id"])
        raise RuntimeError("Owned synthetic interruption after actual financial effect")

    with monkeypatch.context() as fault:
        fault.setattr(PostgresFinancePostingRepository, "post", interrupted)
        with pytest.raises(RuntimeError, match="Owned synthetic interruption"):
            _phase(runtime, reviewed, "post", "poster")
    assert len(completed) == 1 and _business_digest(runtime) == before
    assert _phase(runtime, reviewed, "post", "poster")["phase"] == 2


def test_actual_stale_principal_cannot_replay_saved_ack_after_permission_withdrawal(receipt_database):
    runtime, order = _source(receipt_database, foreign=True)
    reviewed = _phase(runtime, _return(runtime, order, 4, 0), "review", "checker")
    original = _phase(runtime, reviewed, "post", "poster")
    assert _phase(runtime, reviewed, "post", "poster") == original
    with runtime.actor("poster") as (_connection, _, actor):
        principal = current_server_principal()
    assert principal is not None
    with runtime.actor("maker") as (connection, _, revoker):
        connection.execute("""UPDATE reconforge.identity_role_permissions SET active=FALSE,revoked_at=now(),revoked_by=%s,
            revocation_reason_code='access_change',lifecycle_version=lifecycle_version+1
            WHERE tenant_id=%s AND permission_name='finance_core.post'""", (revoker.user_id, runtime.tenant))
    before = _business_digest(runtime)
    with pytest.raises(FinancePostingError) as refused, PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(principal):
        PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant).post(reviewed["id"], expected_plan_digest=reviewed["plan_digest"],
            command_id=reviewed["id"] + ":post", reason="Actual independently governed post", actor=actor)
    assert refused.value.code == "operational_actor_denied"
    assert _business_digest(runtime) == before


def test_actual_scope_withdrawal_commits_during_post_lock_wait_and_prevents_effect(receipt_database):
    runtime, order = _source(receipt_database, foreign=True)
    reviewed = _phase(runtime, _return(runtime, order, 4, 0), "review", "checker")
    with runtime.actor("poster") as (_connection, _, actor):
        principal = current_server_principal()
    assert principal is not None
    before = _business_digest(runtime)
    starting = Queue()

    def waiting_post():
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(principal):
            connection.execute("SET LOCAL lock_timeout='8s'")
            connection.execute("SET LOCAL statement_timeout='15s'")
            starting.put(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
            return PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant).post(reviewed["id"],
                expected_plan_digest=reviewed["plan_digest"], command_id="monetary-post-waits-on-withdrawal",
                reason="Actual post waits for durable current scope admission", actor=actor)

    with ThreadPoolExecutor(max_workers=1) as workers:
        with runtime.actor("maker") as (revoker, _, revoking_actor):
            PostgresScopeAuthorityRepository(revoker).revoke(tenant_id=runtime.tenant, grant_id="cr1-poster-workspace",
                actor_id=revoking_actor.user_id, reason="Independent live monetary source scope withdrawal")
            holder = revoker.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
            future = workers.submit(waiting_post)
            waiter = starting.get(timeout=6)
            with psycopg.connect(runtime.admin_dsn, autocommit=True, connect_timeout=5) as observer:
                deadline = time.monotonic() + 6
                while holder not in observer.execute("SELECT pg_blocking_pids(%s)", (waiter,)).fetchone()[0]:
                    assert time.monotonic() < deadline and not future.done()
                    time.sleep(.025)
            assert not future.done()
        with pytest.raises(FinancePostingError) as refused:
            future.result(timeout=20)
    assert refused.value.code == "operational_scope_denied"
    assert _business_digest(runtime) == before
