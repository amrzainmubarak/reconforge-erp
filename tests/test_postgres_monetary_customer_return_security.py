"""Actual ordinary-role149 SQL, replay, failure and lock-wait authority checks."""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI, Request
from psycopg import sql
from psycopg.rows import dict_row

from reconforge.api.errors import APIError
from reconforge.api.routes import customer_partial_returns_v3 as monetary_routes
from reconforge.domain.finance_posting import FinancePostingError, canonical_json
from reconforge.domain.monetary_customer_partial_return_commands import MonetaryPartialReturnPreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary, set_local_tenant_scope
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_monetary_customer_partial_returns import (
    PostgresMonetaryCustomerPartialReturnsRepository,
)
from reconforge.infrastructure.postgres_monetary_stock_schema import TABLES as MONETARY_TABLES
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.platform.common import current_server_principal, server_principal_context
from tests.customer_partial_return_monetary_posted_oracle import TABLES
from tests.test_postgres_inventory_receipt_posting import receipt_database
from tests.test_postgres_monetary_customer_partial_returns import (
    DAY,
    SCOPE,
    _collect,
    _phase,
    _posted,
    _return,
    _source,
)

_ = receipt_database


@pytest.mark.parametrize("dimension", ["workspace", "organization", "entity"])
def test_monetary_scope_refusal_persists_closed_policy_evidence_before_owner_use(receipt_database, dimension):
    runtime, order = _source(receipt_database, foreign=False)
    before = _business_digest(runtime)
    app = FastAPI()
    app.state.postgres_identity_factory = runtime.factory
    app.state.postgres_finance_core_factory = runtime.factory
    headers = {"x-reconforge-tenant": runtime.tenant, "x-reconforge-workspace": "work",
               "x-reconforge-organization": "org", "x-reconforge-legal-entity": "entity"}
    selected = {"workspace": "x-reconforge-workspace", "organization": "x-reconforge-organization", "entity": "x-reconforge-legal-entity"}[dimension]
    headers[selected] = "ungranted-" + dimension
    request = Request({"type": "http", "method": "GET", "path": f"/api/v3/customer-partial-returns/sources/{order['id']}/balance",
                       "headers": [(key.encode(), value.encode()) for key, value in headers.items()], "app": app})
    request.state.request_id = "synthetic-scope-refusal"
    with runtime.actor("poster") as (_, _, _actor):
        principal = current_server_principal()
        assert principal is not None
        request.state.server_principal = principal
        with pytest.raises(APIError) as refused:
            monetary_routes.execute(request, principal.user, lambda *_args: pytest.fail("A refused scope reached its financial owner."))
    assert refused.value.status_code == 403 and refused.value.code == dimension + "_scope_denied"
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        rows = connection.execute("""SELECT metadata_json FROM reconforge.domain_audit_events
            WHERE tenant_id=%s AND object_type='authorization.policy_decision' AND action='evaluated'""", (runtime.tenant,)).fetchall()
        assert len(rows) == 1
        evidence = rows[0]["metadata_json"]["policy_decision_evidence"]
        assert evidence["allowed"] is False and evidence["reason_code"] == refused.value.code
        assert evidence["context_binding"] == "bound"
        assert PostgresAuditEventRepository(connection, runtime.tenant).verify().ok
    assert _business_digest(runtime) == before


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


@pytest.mark.parametrize("table", ["ar_invoice_lines", "ar_receipt_allocations"])
@pytest.mark.parametrize("wrong_scope", [False, True], ids=["original-scope", "hidden-origin-scope"])
def test_actual_sql_cannot_delete_original_monetary_ar_children(receipt_database, table, wrong_scope):
    runtime, order = _source(receipt_database, foreign=True)
    order = _collect(runtime, order, 4000, rate="1.30", number="IMMUTABLE-AR-CHILD")
    invoice_id = order["monetary_origin"]["invoice_id"]
    before = _business_digest(runtime)
    selected = sql.SQL("SELECT count(*) n FROM reconforge.{} WHERE tenant_id=%s AND invoice_id=%s").format(sql.Identifier(table))
    deleted = sql.SQL("DELETE FROM reconforge.{} WHERE tenant_id=%s AND invoice_id=%s RETURNING invoice_id").format(sql.Identifier(table))
    with runtime.actor("poster") as (connection, _, _actor):
        assert connection.execute(selected, (runtime.tenant, invoice_id)).fetchone()["n"] == 1
        if wrong_scope:
            connection.execute("SELECT set_config('app.workspace_id','wrong-workspace',true)")
            assert connection.execute(selected, (runtime.tenant, invoice_id)).fetchone()["n"] == 0
            cursor = connection.execute(deleted, (runtime.tenant, invoice_id))
            assert cursor.fetchall() == [] and cursor.rowcount == 0
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        else:
            expected = psycopg.errors.RaiseException if table == "ar_invoice_lines" else psycopg.errors.CheckViolation
            with pytest.raises(expected) as refused, connection.transaction():
                connection.execute(deleted, (runtime.tenant, invoice_id))
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
            if table == "ar_invoice_lines":
                assert refused.value.sqlstate == "P0001"
                assert refused.value.diag.message_primary == "approved receivable invoice lines are immutable"
                assert refused.value.diag.constraint_name is None
            else:
                assert refused.value.sqlstate == "23514"
                assert refused.value.diag.constraint_name == "customer_partial_return_monetary_owner"
            assert connection.execute(selected, (runtime.tenant, invoice_id)).fetchone()["n"] == 1
    assert _business_digest(runtime) == before


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
    request = MonetaryPartialReturnPreparation(**SCOPE, organization_code="ORG", entity_code="ENTITY", source_order_id=order["id"],
        quantity_scaled=6, period_id="period", posting_date=DAY, reason="Exact competing monetary intent", expected_history_version=0)

    def prepare_exact(connection, actor, number):
        connection.execute("SET LOCAL lock_timeout='5s'")
        connection.execute("SET LOCAL statement_timeout='10s'")
        return PostgresMonetaryCustomerPartialReturnsRepository(connection, runtime.tenant).prepare(request,
            command_id="concurrent-return" + ("" if same_command else str(number)), actor=actor)

    def contender(number):
        try:
            with runtime.actor("maker") as (connection, _, actor):
                ready.wait(timeout=5)
                return number, "prepared", prepare_exact(connection, actor, number)
        except FinancePostingError as exc:
            if exc.code == "monetary_return_retryable_conflict":
                assert getattr(exc.__cause__, "sqlstate", None) == "55P03"
                return number, "retryable-conflict", None
            assert exc.code == "monetary_return_state_conflict" and not same_command
            return number, "state-conflict", None

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(contender, (1, 2)))
    prepared = [(number, value) for number, kind, value in outcomes if kind == "prepared"]
    assert prepared
    winner_number, saved_ack = prepared[0]
    if same_command:
        assert all(canonical_json(value) == canonical_json(saved_ack) for _number, value in prepared)
    else:
        assert len(prepared) == 1
    # Both contenders are terminal. These are explicit, fresh-transaction
    # retries of identical intent and keys, never an automatic financial retry.
    before_retry = _business_digest(runtime)
    for number in (1, 2):
        with runtime.actor("maker") as (connection, _, actor):
            if same_command or number == winner_number:
                assert canonical_json(prepare_exact(connection, actor, number)) == canonical_json(saved_ack)
            else:
                with pytest.raises(FinancePostingError) as refused, connection.transaction():
                    prepare_exact(connection, actor, number)
                assert refused.value.code == "monetary_return_state_conflict"
        assert _business_digest(runtime) == before_retry
    with runtime.actor("maker") as (connection, _, _actor):
        assert connection.execute("SELECT count(*) n FROM reconforge.customer_partial_return_monetary_plans WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.customer_partial_return_monetary_commands WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.customer_partial_return_monetary_events WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.customer_partial_return_monetary_history WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
        assert connection.execute("""SELECT count(*) n FROM reconforge.finance_posting_effects effect
            JOIN reconforge.customer_partial_return_monetary_entries entry ON(entry.tenant_id,entry.entry_id)=(effect.tenant_id,effect.entry_id)
            WHERE entry.tenant_id=%s""", (runtime.tenant,)).fetchone()["n"] == 0


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


def _prepared_event(runtime, plan):
    with runtime.actor("maker") as (connection, _, _actor):
        rows = connection.execute("""SELECT audit_event_id,outbox_event_id
            FROM reconforge.customer_partial_return_monetary_events
            WHERE tenant_id=%s AND plan_id=%s AND operation='prepare'""", (runtime.tenant, plan["id"])).fetchall()
        assert len(rows) == 1
        return dict(rows[0])


@pytest.mark.parametrize("attack", ["audit-wrong-type", "outbox-wrong-type", "outbox-payload"])
def test_actual_owned_monetary_event_cannot_escape_closure_by_type_or_envelope_mutation(receipt_database, attack):
    runtime, order = _source(receipt_database, foreign=True)
    plan = _return(runtime, order, 4, 0)
    event = _prepared_event(runtime, plan)
    before = _business_digest(runtime)
    with runtime.actor("poster") as (connection, _, _actor):
        audit = attack == "audit-wrong-type"
        query = ("SELECT to_jsonb(r)::text original FROM reconforge.domain_audit_events r WHERE tenant_id=%s AND id=%s" if audit else
                 "SELECT to_jsonb(r)::text original FROM reconforge.outbox_events r WHERE tenant_id=%s AND event_id=%s")
        identifier = event["audit_event_id" if audit else "outbox_event_id"]
        original = connection.execute(query, (runtime.tenant, identifier)).fetchone()["original"]
        with pytest.raises(psycopg.errors.RaiseException) as refused, connection.transaction():
            if audit:
                connection.execute("UPDATE reconforge.domain_audit_events SET object_type='reconciliation_run' WHERE tenant_id=%s AND id=%s",
                                   (runtime.tenant, identifier))
            elif attack == "outbox-wrong-type":
                connection.execute("UPDATE reconforge.outbox_events SET aggregate_type='reconciliation_run' WHERE tenant_id=%s AND event_id=%s",
                                   (runtime.tenant, identifier))
            else:
                connection.execute("UPDATE reconforge.outbox_events SET payload=payload||'{\"unowned_override\":true}'::jsonb WHERE tenant_id=%s AND event_id=%s",
                                   (runtime.tenant, identifier))
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert refused.value.sqlstate == "P0001" and refused.value.diag.constraint_name is None
        assert refused.value.diag.message_primary == ("Domain audit events are append-only" if audit else
                                                      "outbox event identity and payload are immutable")
        assert connection.execute(query, (runtime.tenant, identifier)).fetchone()["original"] == original
    assert _business_digest(runtime) == before


def test_actual_owned_monetary_outbox_delivery_requires_no_private_financial_table_read(receipt_database):
    runtime, order = _source(receipt_database, foreign=True)
    plan = _return(runtime, order, 4, 0)
    event = _prepared_event(runtime, plan)
    before = _business_digest(runtime)
    identifier = event["outbox_event_id"]
    role = "monetary_delivery_worker_" + uuid4().hex[:12]
    private_tables = (*MONETARY_TABLES, *("operational_fx_" + suffix for suffix in ("sources", "plans", "reviews", "links", "commands")))
    delivery_fields = {"status", "attempt_count", "available_at", "claimed_at", "claimed_by", "published_at",
                       "last_error", "dead_lettered_at", "lease_generation"}
    original_query = "SELECT to_jsonb(r) original FROM reconforge.outbox_events r WHERE tenant_id=%s AND event_id=%s"
    delivery_query = "SELECT lease_generation,action,worker_id,attempts FROM reconforge.outbox_delivery_evidence WHERE tenant_id=%s AND event_id=%s"
    with psycopg.connect(runtime.admin_dsn, row_factory=dict_row) as admin:
        original = admin.execute(original_query, (runtime.tenant, identifier)).fetchone()["original"]
        assert original["aggregate_type"] == "operational_finance" and original["aggregate_id"] == plan["id"]
        assert original["event_type"] == "customer_partial_return_monetary_prepare"
        assert original["payload"]["plan_digest"] == plan["plan_digest"]
        assert original["payload"]["audit_event_id"] == event["audit_event_id"]
        assert all(original[key] == value for key, value in SCOPE.items())
        assert original["status"] == "Pending" and original["attempt_count"] == original["lease_generation"] == 0
        prior_evidence = admin.execute(delivery_query, (runtime.tenant, identifier)).fetchall()
        assert prior_evidence == []
        assert admin.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone() is None
        try:
            # All role/grant and delivery changes are transaction-contained.
            # Force the deferred checks while still the minimal worker, then
            # roll back; a killed fixture cannot leave a cluster role behind.
            admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
                          .format(sql.Identifier(role)))
            admin.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("GRANT SELECT ON reconforge.outbox_events,reconforge.outbox_delivery_evidence TO {}")
                          .format(sql.Identifier(role)))
            admin.execute(sql.SQL("""GRANT UPDATE(status,attempt_count,available_at,claimed_at,claimed_by,
                published_at,last_error,dead_lettered_at,lease_generation) ON reconforge.outbox_events TO {}""")
                          .format(sql.Identifier(role)))
            admin.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            set_local_tenant_scope(admin, runtime.tenant, **SCOPE)
            flags = admin.execute("SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication "
                                  "FROM pg_roles WHERE rolname=current_user").fetchone()
            assert all(value is False for value in flags.values())
            assert len(MONETARY_TABLES) == 7 and len(private_tables) == len(set(private_tables)) == 12
            rights = admin.execute("SELECT has_column_privilege(current_user,'reconforge.outbox_events','status','UPDATE') delivery,"
                "has_column_privilege(current_user,'reconforge.outbox_events','payload','UPDATE') payload,"
                "has_column_privilege(current_user,'reconforge.outbox_events','tenant_id','UPDATE') tenant").fetchone()
            assert rights == {"delivery": True, "payload": False, "tenant": False}
            for table in private_tables:
                allowed = admin.execute("SELECT has_table_privilege(current_user,%s,'SELECT') whole,"
                    "has_any_column_privilege(current_user,%s,'SELECT') any_column", ("reconforge." + table,) * 2).fetchone()
                assert allowed == {"whole": False, "any_column": False}
                with pytest.raises(psycopg.errors.InsufficientPrivilege) as denied, admin.transaction():
                    admin.execute(sql.SQL("SELECT tenant_id FROM reconforge.{} LIMIT 1").format(sql.Identifier(table)))
                assert denied.value.sqlstate == "42501"
            assert admin.execute(original_query, (runtime.tenant, identifier)).fetchone()["original"] == original
            claimed = admin.execute("""UPDATE reconforge.outbox_events SET status='Claimed',claimed_by=%s,
                claimed_at=clock_timestamp()+interval '60 seconds',attempt_count=attempt_count+1,lease_generation=lease_generation+1
                WHERE tenant_id=%s AND event_id=%s RETURNING event_id,lease_generation""", (role, runtime.tenant, identifier)).fetchall()
            assert claimed == [{"event_id": identifier, "lease_generation": 1}]
            admin.execute("SET CONSTRAINTS ALL IMMEDIATE")
            published = admin.execute("""UPDATE reconforge.outbox_events SET status='Published',claimed_at=NULL,claimed_by=NULL,
                published_at=clock_timestamp(),last_error=NULL WHERE tenant_id=%s AND event_id=%s RETURNING event_id""",
                (runtime.tenant, identifier)).fetchall()
            assert published == [{"event_id": identifier}]
            admin.execute("SET CONSTRAINTS ALL IMMEDIATE")
            after = admin.execute(original_query, (runtime.tenant, identifier)).fetchone()["original"]
            assert after["status"] == "Published" and after["lease_generation"] == after["attempt_count"] == 1
            assert {key: value for key, value in original.items() if key not in delivery_fields} == {
                key: value for key, value in after.items() if key not in delivery_fields}
            evidence = admin.execute(delivery_query, (runtime.tenant, identifier)).fetchall()
            assert len(evidence) == 2 and {row["action"] for row in evidence} == {"claimed", "published"}
            assert all(row["worker_id"] == role and row["lease_generation"] == row["attempts"] == 1 for row in evidence)
        finally:
            admin.rollback()
        assert admin.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone() is None
        assert admin.execute(original_query, (runtime.tenant, identifier)).fetchone()["original"] == original
        assert admin.execute(delivery_query, (runtime.tenant, identifier)).fetchall() == prior_evidence
    assert _business_digest(runtime) == before
