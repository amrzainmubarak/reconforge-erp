"""Real nonowner raw-admission and migration closure for reviewed receipt storage."""
from __future__ import annotations

import json
import os
from typing import Any

import pytest

from reconforge.domain.finance_posting import canonical_json
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_posting_schema import install_postgres_finance_posting_schema
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from tests.test_postgres_inventory_receipt_posting import (
    ReceiptRuntime,
    prepare_and_review,
    receipt_database,  # noqa: F401 - shared owned disposable fixture
)
from tests.test_postgres_inventory_receipt_posting import (
    receipt_runtime as _receipt_runtime,
)

receipt_runtime = _receipt_runtime

pytestmark = pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"), reason="requires owned live PostgreSQL fixture")


def committed(runtime: ReceiptRuntime) -> tuple[Any, Any, Any]:
    plan, review = prepare_and_review(runtime)
    with runtime.actor("poster") as (_, repository, actor):
        effect = repository.commit(plan["plan_id"], command_id="commit", expected_review_digest=review["review_digest"], reason="Complete synthetic source", actor=actor)
    return plan, review, effect


def ordinary(runtime: ReceiptRuntime, *, number: str = "LEGACY", kind: str = "Receipt", quantity: str = "10") -> str:
    with runtime.actor("maker") as (connection, _, __):
        line = {"item_code": "ITEM", "quantity": quantity,
                "from_location": "MAIN/STOCK" if kind == "Delivery" else "",
                "to_location": "MAIN/STOCK" if kind == "Receipt" else ""}
        result = PostgresInventoryCoreRepository(connection, runtime.tenant).create_movement(
            movement_number=number, movement_type=kind, organization_code="ORG", entity_code="ENTITY",
            period_id="period", movement_date="2026-10-05", description="Synthetic ordinary movement", lines=[line], workspace="work")
        return str(result["id"])


def raw_post(connection: Any, tenant: str, identifier: str) -> None:
    connection.execute("UPDATE reconforge.inventory_movements SET status='Posted',posted_by='poster',posted_at=now(),post_reason='Synthetic raw posting' WHERE tenant_id=%s AND id=%s", (tenant, identifier))


def test_nonowner_capability_and_all_new_tables_force_scoped_rls(receipt_runtime: ReceiptRuntime) -> None:
    runtime = receipt_runtime
    plan, _, _ = committed(runtime)
    with runtime.actor("poster") as (connection, _, __):
        caps = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        assert not caps["rolsuper"] and not caps["rolbypassrls"]
        states = connection.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE relnamespace='reconforge'::regnamespace AND relname IN ('inventory_receipt_plans','inventory_receipt_reviews','inventory_receipt_links','inventory_receipt_commands')").fetchall()
        assert len(states) == 4 and all(row[0] and row[1] for row in states)
        for guc, value in (("app.tenant_id", "hidden"), ("app.workspace_id", "hidden"), ("app.organization_id", "hidden"), ("app.legal_entity_id", "hidden"), ("app.entity_id", "hidden")):
            with connection.transaction(force_rollback=True):
                connection.execute("SELECT set_config(%s,%s,true)", (guc, value))
                assert connection.execute("SELECT 1 FROM reconforge.inventory_receipt_plans WHERE id=%s", (plan["plan_id"],)).fetchone() is None
                assert connection.execute("SELECT 1 FROM reconforge.inventory_receipt_links").fetchone() is None


@pytest.mark.parametrize("value", ["IRP1-ABSENT", "irp1-absent", "IrP1-Absent"])
@pytest.mark.parametrize("column", ["id", "movement_number"])
def test_unconditional_reserved_namespace_absence_is_not_legacy_exemption(receipt_runtime: ReceiptRuntime, column: str, value: str) -> None:
    import psycopg
    from psycopg import sql
    runtime = receipt_runtime
    identifier = ordinary(runtime)
    with runtime.actor("poster") as (connection, _, __):
        with pytest.raises(psycopg.errors.CheckViolation, match="namespace|relabeled"), connection.transaction():
            connection.execute(sql.SQL("UPDATE reconforge.inventory_movements SET {}=%s WHERE tenant_id=%s AND id=%s").format(sql.Identifier(column)), (value, runtime.tenant, identifier))
        assert connection.execute("SELECT status FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s", (runtime.tenant, identifier)).fetchone()[0] == "Draft"


@pytest.mark.parametrize("table,column,value", [
    ("inventory_receipt_plans", "reason", "Changed"),
    ("inventory_receipt_reviews", "reason", "Changed"),
    ("inventory_receipt_links", "reason", "Changed"),
    ("inventory_receipt_commands", "request_digest", "0" * 64),
    ("inventory_movements", "status", "Voided"),
    ("inventory_valuation_documents", "status", "Draft"),
    ("finance_entries", "status", "Draft"),
])
def test_committed_source_components_cannot_be_rewritten(receipt_runtime: ReceiptRuntime, table: str, column: str, value: str) -> None:
    import psycopg
    from psycopg import sql
    runtime = receipt_runtime
    committed(runtime)
    with runtime.actor("poster") as (connection, _, __), pytest.raises(psycopg.Error), connection.transaction():
        connection.execute(sql.SQL("UPDATE reconforge.{} SET {}=%s WHERE tenant_id=%s").format(sql.Identifier(table), sql.Identifier(column)), (value, runtime.tenant))


def test_incomplete_source_reservation_cannot_commit(receipt_runtime: ReceiptRuntime) -> None:
    import psycopg

    from reconforge.platform.common import utc_now_text
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    with pytest.raises(psycopg.Error), runtime.actor("poster") as (_, repository, actor):
        audit, outbox = repository._event(plan, "inventory_receipt_committed", actor, repository._metadata(plan, review, committed=True))
        repository._insert("inventory_receipt_links", {"tenant_id": runtime.tenant, "id": plan["plan_id"], "plan_id": plan["plan_id"],
            **{key: plan["scope"][key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
            "review_id": review["review_id"], "plan_digest": plan["plan_digest"], "review_digest": review["review_digest"],
            **{key: value for key, value in plan["artifacts"].items() if key.endswith("_id")},
            "original_plan_id": None, "original_posting_effect_id": None, "posted_actor_id": actor.user_id,
            "posted_at": utc_now_text(), "reason": "Incomplete", "audit_event_id": audit, "outbox_event_id": outbox})
    with runtime.actor("poster") as (connection, _, __):
        assert connection.execute("SELECT 1 FROM reconforge.inventory_receipt_links WHERE tenant_id=%s", (runtime.tenant,)).fetchone() is None
        assert connection.execute("SELECT 1 FROM reconforge.domain_audit_events WHERE tenant_id=%s AND action='inventory_receipt_committed'", (runtime.tenant,)).fetchone() is None


@pytest.mark.parametrize("populated", [False, True])
def test_current_installer_twice_preserves_owner_transaction_and_source(receipt_runtime: ReceiptRuntime, populated: bool) -> None:
    import psycopg
    runtime = receipt_runtime
    plan, _, effect = committed(runtime) if populated else (None, None, None)
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute("CREATE TEMP TABLE receipt_installer_marker(value INTEGER)")
        admin.execute("INSERT INTO receipt_installer_marker VALUES(1)")
        before = admin.execute("SELECT txid_current()").fetchone()[0]
        install_postgres_finance_posting_schema(admin)
        install_postgres_finance_posting_schema(admin)
        assert admin.execute("SELECT txid_current()").fetchone()[0] == before
        assert admin.execute("SELECT value FROM receipt_installer_marker").fetchone()[0] == 1
        admin.rollback()
        assert admin.execute("SELECT to_regclass('pg_temp.receipt_installer_marker')").fetchone()[0] is None
    if populated:
        with runtime.actor("poster") as (_, repository, actor):
            assert repository.get_effect(plan["plan_id"], actor=actor) == effect


def test_canonical_json_digest_agrees_for_unicode_escapes_and_int64(receipt_runtime: ReceiptRuntime) -> None:
    from reconforge.domain.finance_posting import digest_payload
    value = {"Arabic": "مراجعة", "escape": "a\\b\n\t\"", "max": 9_000_000_000_000_000_000, "z": [None, True, False, {"a": 1}]}
    with receipt_runtime.actor("poster") as (connection, _, __):
        actual = connection.execute("SELECT reconforge.irp_canonical(%s::jsonb),reconforge.irp_digest(%s::jsonb)", (json.dumps(value), json.dumps(value))).fetchone()
        assert actual[0] == canonical_json(value)
        assert actual[1] == digest_payload(value)


def test_raw_repeatable_read_posting_is_refused_and_unrelated_read_committed_still_posts(receipt_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = receipt_runtime
    identifier = ordinary(runtime)
    with runtime.factory.connect() as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        connection.execute("SELECT set_config('app.tenant_id',%s,true)", (runtime.tenant,))
        with pytest.raises(psycopg.errors.CheckViolation, match="READ COMMITTED"), connection.transaction():
            raw_post(connection, runtime.tenant, identifier)
        assert connection.execute("SELECT status FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s", (runtime.tenant, identifier)).fetchone()[0] == "Draft"
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        raw_post(connection, runtime.tenant, identifier)
        assert connection.execute("SELECT status FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s", (runtime.tenant, identifier)).fetchone()[0] == "Posted"


def inverse_plan(runtime: ReceiptRuntime, plan: Any) -> tuple[Any, Any]:
    from reconforge.domain.inventory_receipt_posting import ReceiptReversalPreparation
    with runtime.actor("maker") as (_, repository, actor):
        inverse = repository.prepare_reversal(ReceiptReversalPreparation(original_plan_id=plan["plan_id"], reversal_number="INVERSE", posting_date="2026-10-04", period_id="period", reason="Unused source correction"), command_id="inverse-prepare", actor=actor)
    with runtime.actor("checker") as (_, repository, actor):
        review = repository.review(inverse["plan_id"], command_id="inverse-review", expected_plan_digest=inverse["plan_digest"], reason="Confirmed unused source", actor=actor)
    return inverse, review


def wait_lock(runtime: ReceiptRuntime, pid: int) -> None:
    import time

    import psycopg
    deadline = time.monotonic() + 8
    with psycopg.connect(runtime.admin_dsn, autocommit=True) as admin:
        while time.monotonic() < deadline:
            row = admin.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (pid,)).fetchone()
            if row and row[0] == "Lock":
                return
            time.sleep(0.025)
    raise AssertionError("Expected an actual database lock wait before releasing the first transaction")


@pytest.mark.parametrize("inverse_first", [False, True])
def test_raw_outbound_and_unused_inverse_serialize_both_orders(receipt_runtime: ReceiptRuntime, inverse_first: bool) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue

    import psycopg

    from reconforge.domain.finance_posting import FinancePostingError
    runtime = receipt_runtime
    plan, _, effect = committed(runtime)
    inverse, review = inverse_plan(runtime, plan)
    delivery = ordinary(runtime, kind="Delivery", quantity="1")
    pids: Queue[int] = Queue()
    def finish_inverse() -> None:
        with runtime.actor("poster") as (connection, repository, actor):
            pids.put(connection.info.backend_pid)
            repository.commit(inverse["plan_id"], command_id="inverse-commit", expected_review_digest=review["review_digest"], reason="Full inverse", actor=actor)
    def finish_delivery() -> None:
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity") as connection:
            pids.put(connection.info.backend_pid)
            raw_post(connection, runtime.tenant, delivery)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with runtime.actor("poster") as (connection, repository, actor):
            if inverse_first:
                repository.commit(inverse["plan_id"], command_id="inverse-commit", expected_review_digest=review["review_digest"], reason="Full inverse", actor=actor)
                future = pool.submit(finish_delivery)
            else:
                raw_post(connection, runtime.tenant, delivery)
                future = pool.submit(finish_inverse)
            wait_lock(runtime, pids.get(timeout=8))
        with pytest.raises((psycopg.errors.CheckViolation, FinancePostingError)):
            future.result(timeout=15)
    with runtime.actor("poster") as (connection, _, __):
        assert connection.execute("SELECT status FROM reconforge.inventory_movements WHERE tenant_id=%s AND id=%s", (runtime.tenant, delivery)).fetchone()[0] == ("Draft" if inverse_first else "Posted")
        assert connection.execute("SELECT remaining_quantity_scaled FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s", (runtime.tenant, effect["cost_layer_id"])).fetchone()[0] == (0 if inverse_first else 10)


def test_entity_scope_still_cannot_mutate_shared_finance_reference(receipt_runtime: ReceiptRuntime) -> None:
    runtime = receipt_runtime
    plan, _, _ = committed(runtime)
    with runtime.actor("poster") as (connection, _, __):
        assert connection.execute("UPDATE reconforge.finance_journals SET active=FALSE WHERE tenant_id=%s AND id=%s RETURNING id", (runtime.tenant, plan["mapping"]["journal_id"])).fetchone() is None
        assert connection.execute("SELECT active FROM reconforge.finance_journals WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["mapping"]["journal_id"])).fetchone()[0]


def test_raw_draft_line_cannot_be_reparented_to_posted_consumer_after_inverse(receipt_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = receipt_runtime
    plan, _, _ = committed(runtime)
    inverse, review = inverse_plan(runtime, plan)
    with runtime.actor("poster") as (_, repository, actor):
        repository.commit(inverse["plan_id"], command_id="inverse", expected_review_digest=review["review_digest"], reason="Full inverse", actor=actor)
    draft = ordinary(runtime, number="DRAFT-OUTBOUND", kind="Delivery", quantity="1")
    with runtime.actor("poster") as (connection, _, __):
        # Historical INSERT accepts an empty Posted header. It cannot gain a line.
        connection.execute("INSERT INTO reconforge.inventory_movements SELECT (jsonb_populate_record(NULL::reconforge.inventory_movements,to_jsonb(m)||jsonb_build_object('id','empty-posted','movement_number','EMPTY-POSTED','status','Posted'))).* FROM reconforge.inventory_movements m WHERE tenant_id=%s AND id=%s", (runtime.tenant, draft))
        with pytest.raises(psycopg.Error, match="locked Draft parent|posted inventory movement lines are immutable"), connection.transaction():
            connection.execute("UPDATE reconforge.inventory_movement_lines SET movement_id='empty-posted' WHERE tenant_id=%s AND movement_id=%s", (runtime.tenant, draft))
        assert connection.execute("SELECT count(*) FROM reconforge.inventory_movement_lines WHERE tenant_id=%s AND movement_id='empty-posted'", (runtime.tenant,)).fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [("reason", " untrimmed"), ("reason", "bad\nreason"), ("reason", "\u00a0untrimmed"), ("prepared_at", "2026-10-03T24:00:00Z"), ("prepared_at", "2026-02-30T12:00:00Z"), ("quantity_precision", 7), ("quantity_scaled", 0), ("source_number", "lowercase"), ("operation", "Unknown")])
def test_raw_plan_rejects_noncanonical_or_invalid_scalar_content(receipt_runtime: ReceiptRuntime, field: str, value: Any) -> None:
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb
    runtime = receipt_runtime
    plan, _ = prepare_and_review(runtime)
    with runtime.actor("poster") as (connection, _, __):
        row = dict(connection.execute("SELECT * FROM reconforge.inventory_receipt_plans WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["plan_id"])).fetchone())
        row[field] = value
        columns = list(row)
        values = [Jsonb(row[key]) if key == "plan_json" else row[key] for key in columns]
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(sql.SQL("INSERT INTO reconforge.inventory_receipt_plans({}) VALUES({})").format(sql.SQL(',').join(map(sql.Identifier, columns)), sql.SQL(',').join(sql.Placeholder() for _ in columns)), values)


@pytest.mark.parametrize("operation,wrong_actor", [("prepare_receipt", "checker"), ("review", "poster"), ("commit", "checker")])
def test_raw_command_cannot_substitute_retained_source_actor(receipt_runtime: ReceiptRuntime, operation: str, wrong_actor: str) -> None:
    import psycopg
    runtime = receipt_runtime
    committed(runtime)
    with runtime.actor("poster") as (connection, _, __), pytest.raises(psycopg.errors.CheckViolation, match="actor"), connection.transaction():
        connection.execute("INSERT INTO reconforge.inventory_receipt_commands SELECT (jsonb_populate_record(NULL::reconforge.inventory_receipt_commands,to_jsonb(c)||jsonb_build_object('command_id','borrowed-command','actor_user_id',%s::text))).* FROM reconforge.inventory_receipt_commands c WHERE tenant_id=%s AND operation=%s", (wrong_actor, runtime.tenant, operation))



@pytest.mark.parametrize("receipt_first", [False, True])
def test_required_dimension_and_receipt_serialize_both_orders(receipt_runtime: ReceiptRuntime, receipt_first: bool) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue

    from reconforge.domain.finance_posting import FinancePostingError
    runtime = receipt_runtime
    plan, review = prepare_and_review(runtime)
    pids: Queue[int] = Queue()
    def add_dimension(connection) -> None:
        connection.execute("INSERT INTO reconforge.finance_dimensions(tenant_id,id,workspace_id,organization_code,dimension_code,name,dimension_type,required_on_entries,active,created_at,updated_at) VALUES(%s,'new-required','work','ORG','REQUIRED','Synthetic required','Text',TRUE,TRUE,'2026-10-03T00:00:00Z','2026-10-03T00:00:00Z')", (runtime.tenant,))
    def dimension_worker() -> None:
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org") as connection:
            pids.put(connection.info.backend_pid)
            add_dimension(connection)
    def receipt_worker() -> Any:
        with runtime.actor("poster") as (connection, repository, actor):
            pids.put(connection.info.backend_pid)
            return repository.commit(plan["plan_id"], command_id="commit", expected_review_digest=review["review_digest"], reason="Dimension ordering", actor=actor)
    with ThreadPoolExecutor(max_workers=1) as pool:
        if receipt_first:
            with runtime.actor("poster") as (_, repository, actor):
                effect = repository.commit(plan["plan_id"], command_id="commit", expected_review_digest=review["review_digest"], reason="Dimension ordering", actor=actor)
                future = pool.submit(dimension_worker)
                wait_lock(runtime, pids.get(timeout=8))
            future.result(timeout=10)
            with runtime.actor("poster") as (_, repository, actor):
                assert repository.get_effect(plan["plan_id"], actor=actor) == effect
                assert repository.commit(plan["plan_id"], command_id="commit", expected_review_digest=review["review_digest"], reason="Dimension ordering", actor=actor) == effect
        else:
            with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org") as connection:
                add_dimension(connection)
                future = pool.submit(receipt_worker)
                wait_lock(runtime, pids.get(timeout=8))
            with pytest.raises(FinancePostingError, match="required Finance dimensions"):
                future.result(timeout=10)
            with runtime.actor("poster") as (connection, _, __):
                assert connection.execute("SELECT 1 FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone() is None
                assert connection.execute("SELECT 1 FROM reconforge.inventory_receipt_links WHERE tenant_id=%s", (runtime.tenant,)).fetchone() is None


@pytest.mark.parametrize("after_inverse", [False, True])
def test_reserved_layer_raw_history_requires_capacity_and_final_approved_balance(receipt_runtime: ReceiptRuntime, after_inverse: bool) -> None:
    import psycopg
    runtime = receipt_runtime
    plan, _, effect = committed(runtime)
    delivery = ordinary(runtime, kind="Delivery", quantity="1")
    with runtime.actor("poster") as (connection, _, __):
        line = connection.execute("SELECT id FROM reconforge.inventory_movement_lines WHERE tenant_id=%s AND movement_id=%s", (runtime.tenant, delivery)).fetchone()[0]
        connection.execute("INSERT INTO reconforge.inventory_valuation_documents SELECT (jsonb_populate_record(NULL::reconforge.inventory_valuation_documents,to_jsonb(v)||jsonb_build_object('id','raw-draft-val','movement_id',%s::text,'valuation_number','RAW-DRAFT-VAL','status','Draft','total_value_minor',0,'finance_entry_id',NULL,'approved_by','','approved_at',NULL,'approval_reason',''))).* FROM reconforge.inventory_valuation_documents v WHERE tenant_id=%s AND id=%s", (delivery, runtime.tenant, plan['artifacts']['valuation_document_id']))
        connection.execute("INSERT INTO reconforge.inventory_valuation_lines SELECT (jsonb_populate_record(NULL::reconforge.inventory_valuation_lines,to_jsonb(v)||jsonb_build_object('id','raw-outbound-line','valuation_document_id','raw-draft-val','movement_line_id',%s::text,'flow_direction','Outbound','quantity_scaled',1,'value_minor',1200))).* FROM reconforge.inventory_valuation_lines v WHERE tenant_id=%s AND id=%s", (line, runtime.tenant, plan['artifacts']['valuation_line_id']))
    if after_inverse:
        inverse, review = inverse_plan(runtime, plan)
        with runtime.actor("poster") as (_, repository, actor):
            repository.commit(inverse["plan_id"], command_id="inverse", expected_review_digest=review["review_digest"], reason="Full inverse", actor=actor)
    with pytest.raises(psycopg.errors.CheckViolation, match="remaining source capacity|final Approved valuation"), runtime.actor("poster") as (connection, _, __):
        connection.execute("INSERT INTO reconforge.inventory_layer_consumptions(tenant_id,id,workspace_id,valuation_line_id,cost_layer_id,quantity_scaled,value_minor) VALUES(%s,'raw-history','work','raw-outbound-line',%s,1,1200)", (runtime.tenant, effect["cost_layer_id"]))
    with runtime.actor("poster") as (connection, repository, actor):
        assert connection.execute("SELECT 1 FROM reconforge.inventory_layer_consumptions WHERE tenant_id=%s AND id='raw-history'", (runtime.tenant,)).fetchone() is None
        assert repository.get_effect(plan["plan_id"], actor=actor) == effect


def test_reserved_layer_missing_residual_update_rolls_back_approved_legacy_consumer(receipt_runtime: ReceiptRuntime) -> None:
    import psycopg

    from reconforge.infrastructure.postgres_inventory_valuation import PostgresInventoryValuationRepository
    runtime = receipt_runtime
    plan, _, effect = committed(runtime)
    delivery = ordinary(runtime, kind="Delivery", quantity="1")
    with runtime.actor("checker") as (connection, _, actor):
        PostgresInventoryCoreRepository(connection, runtime.tenant).post_movement(delivery, reason="Physical delivery", actor_label=actor.username)
    with runtime.actor("maker") as (connection, _, actor):
        document = PostgresInventoryValuationRepository(connection, runtime.tenant).create_document(valuation_number="ORDINARY-ISSUE", movement_id=delivery, policy_code="FIFO", actor_label=actor.username)
    class MissingResidualUpdate:
        def __init__(self, connection):
            self.connection = connection
        def __getattr__(self, key):
            return getattr(self.connection, key)
        def execute(self, query, parameters=None):
            if isinstance(query, str) and query.startswith("UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=remaining_quantity_scaled-"):
                return self.connection.execute("SELECT 1")
            return self.connection.execute(query, parameters)
    with pytest.raises(psycopg.errors.CheckViolation, match="final balance"), runtime.actor("checker") as (connection, _, actor):
        approved = PostgresInventoryValuationRepository(MissingResidualUpdate(connection), runtime.tenant).approve_document(document["id"], reason="Cost review with injected missing update", actor_label=actor.username)
        assert approved["status"] == "Approved"
    with runtime.actor("poster") as (connection, repository, actor):
        assert connection.execute("SELECT status FROM reconforge.inventory_valuation_documents WHERE tenant_id=%s AND id=%s", (runtime.tenant, document["id"])).fetchone()[0] == "Draft"
        assert connection.execute("SELECT 1 FROM reconforge.inventory_layer_consumptions WHERE tenant_id=%s", (runtime.tenant,)).fetchone() is None
        assert repository.get_effect(plan["plan_id"], actor=actor) == effect


def test_reserved_layer_residual_only_update_cannot_fabricate_history(receipt_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = receipt_runtime
    plan, _, effect = committed(runtime)
    with runtime.actor("poster") as (connection, repository, actor):
        with pytest.raises(psycopg.Error, match="immutable consumption and reversal records"), connection.transaction():
            connection.execute("UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=9,remaining_value_minor=10800,row_version=row_version+1 WHERE tenant_id=%s AND id=%s", (runtime.tenant, effect["cost_layer_id"]))
        assert repository.get_effect(plan["plan_id"], actor=actor) == effect


def test_receipt_identifier_validation_preserves_v_and_rejects_unicode_whitespace(receipt_runtime: ReceiptRuntime) -> None:
    with receipt_runtime.actor("poster") as (connection, _, __):
        for value in ("rev", "vouch", "value"):
            assert connection.execute("SELECT reconforge.irp_text(%s)", (value,)).fetchone()[0]
        for value in ("\vrev", "rev\v", "\u00a0rev", "rev\u00a0"):
            assert not connection.execute("SELECT reconforge.irp_text(%s)", (value,)).fetchone()[0]
