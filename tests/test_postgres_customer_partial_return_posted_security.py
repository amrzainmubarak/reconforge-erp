"""Independent actual posted-cycle and ordinary-app abuse checks.

No native test here is qualified by collection or by the pure expectation tests.
Each fixture creates synthetic originals through the genuine existing owners.
Private row captures stay in memory; failures expose constant diagnostics only.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Barrier
from threading import Event as ThreadEvent
from typing import Any

import psycopg
import pytest
from psycopg import sql

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.sales_revenue import SalesInvoicePreparation
from reconforge.infrastructure.postgres_customer_partial_returns import PostgresCustomerPartialReturnsRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from tests.customer_partial_return_posted_cycle_oracle import (
    TABLES,
    Consumption,
    Event,
    ExpectedEffect,
    OriginalSale,
    decode_row,
    expected_cycle,
    qualify_raw_cycle,
    require,
    verify_posted_gl_amount_delta,
)
from tests.test_postgres_commercial_collections import complete, prepare
from tests.test_postgres_customer_partial_return_source import two_layer_source
from tests.test_postgres_customer_partial_returns import (
    SCOPE,
    balance,
    create_partial_runtime,
    phase,
    posted,
    prepare_refund,
    prepare_return,
    prepare_reversal,
    request,
)
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database
from tests.test_postgres_stock_sales import create_reserved_order, execute, repository

_ = receipt_database
GL_TABLES = ("finance_posting_effects", "finance_entries", "finance_entry_lines")


def rows(runtime: ReceiptRuntime, table: str) -> tuple[dict[str, Any], ...]:
    with runtime.actor("maker") as (connection, _, _actor):
        result = connection.execute(sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text")
                                    .format(sql.Identifier(table)), (runtime.tenant,)).fetchall()
    return tuple(decode_row(item["original"]) for item in result)


def ledger(runtime: ReceiptRuntime) -> dict[str, tuple[dict[str, Any], ...]]:
    return {name: rows(runtime, name) for name in GL_TABLES}


def retained(runtime: ReceiptRuntime) -> dict[str, tuple[str, ...]]:
    """Independent byte-text custody, including every new owner table."""
    with runtime.actor("maker") as (connection, _, _actor):
        names = connection.execute("""SELECT table_name FROM information_schema.tables
            WHERE table_schema='reconforge' AND table_type='BASE TABLE'
            AND table_name ~ '^(customer_partial_return_|customer_return_|stock_|finance_|ar_|inventory_|operational_finance_|domain_audit_|outbox_)'
            ORDER BY table_name""").fetchall()
        return {item["table_name"]: tuple(row["original"] for row in connection.execute(
            sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text")
            .format(sql.Identifier(item["table_name"])), (runtime.tenant,)).fetchall()) for item in names}


def capture(runtime: ReceiptRuntime) -> dict[str, tuple[str, ...]]:
    with runtime.actor("maker") as (connection, _, _actor):
        return {name: tuple(row["original"] for row in connection.execute(
            sql.SQL("SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text COLLATE \"C\"")
            .format(sql.Identifier(name)), (runtime.tenant,)).fetchall()) for name in TABLES}


def unchanged(before: object, after: object) -> None:
    require(before == after)


def original_vector(runtime: ReceiptRuntime, source_id: str) -> OriginalSale:
    stock = next(row for row in rows(runtime, "stock_sales_orders") if row["id"] == source_id)
    native = rows(runtime, "inventory_layer_consumptions")
    allocations = stock["issue_plan"]["allocations"]
    consumed = []
    for position, allocation in enumerate(allocations, 1):
        matches = [row for row in native if row["cost_layer_id"] == allocation["cost_layer_id"]]
        require(len(matches) == 1)
        row = matches[0]
        consumed.append(Consumption(position, row["id"], row["cost_layer_id"], row["quantity_scaled"], row["value_minor"]))
    # Independent hand-derived fixture inputs, checked against original SQL.
    require([(r.quantity_scaled, r.value_minor) for r in consumed] == [(10, 12000), (5, 10000)])
    require([r.layer_id for r in consumed] != sorted(r.layer_id for r in consumed))
    invoice = next(row for row in rows(runtime, "ar_invoices") if row["id"] == stock["invoice_id"])
    allocations_native = rows(runtime, "ar_receipt_allocations")
    collected = sum(row["amount_minor"] for row in allocations_native if row["invoice_id"] == invoice["id"])
    require((stock["quantity_scaled"], stock["quantity_precision"], invoice["total_minor"], collected) == (15, 0, 67500, 10000))
    return OriginalSale(stock["quantity_precision"], stock["quantity_scaled"], invoice["total_minor"], collected,
                        invoice["currency_code"], invoice["currency_precision"], tuple(consumed))


def account_roles(runtime: ReceiptRuntime) -> dict[str, str]:
    accounts = rows(runtime, "finance_accounts")
    result = {row["account_code"]: row["id"] for row in accounts
              if row["account_code"] in {"AR", "REVENUE", "INVENTORY", "COGS", "REFUND", "CASH"}}
    require(len(result) == 6)
    return result


def verify_economics(runtime: ReceiptRuntime, source: OriginalSale, expected: ExpectedEffect,
                     plan: dict[str, Any] | None, old_gl: dict[str, tuple[dict[str, Any], ...]],
                     old_layers: tuple[dict[str, Any], ...], old_consumptions: tuple[dict[str, Any], ...]) -> None:
    verify_posted_gl_amount_delta(source, expected, old_gl, ledger(runtime), account_roles(runtime))
    unchanged(old_consumptions, rows(runtime, "inventory_layer_consumptions"))
    history = sorted(rows(runtime, "customer_partial_return_history"), key=lambda row: row["sequence"])
    require([row["sequence"] for row in history] == list(range(1, len(history) + 1)))
    require(len(history) == expected.event.expected_history_version + 1 and history[-1]["kind"] == expected.event.kind)
    if plan is not None:
        require(plan["phase"] == 2 and history[-1]["plan_id"] == plan["id"])
        require(len(plan["entries"]) == (2 if expected.portions else 1))
        effects = {row["id"]: row for row in rows(runtime, "finance_posting_effects")}
        require(all(part["posting_effect_id"] in effects and effects[part["posting_effect_id"]]["entry_id"] == part["entry_id"]
                    for part in plan["entries"]))
        restorations = [row for row in rows(runtime, "customer_partial_return_restorations") if row["plan_id"] == plan["id"]]
        require(len(restorations) == len(expected.portions))
        direction = -1 if expected.event.kind == "ReverseReturn" else 1
        for portion in expected.portions:
            selected = [row for row in restorations if row["position"] == portion.position]
            require(len(selected) == 1)
            row = selected[0]
            require((row["original_consumption_id"], row["cost_layer_id"], row["offset_quantity_scaled"],
                     row["quantity_scaled"], row["value_minor"], row["direction"]) ==
                    (portion.consumption_id, portion.layer_id, portion.offset_quantity_scaled,
                     portion.quantity_scaled, portion.value_minor, direction))
            original = next(item for item in old_consumptions if item["id"] == portion.consumption_id)
            require(row["original_valuation_line_id"] == original["valuation_line_id"]
                    and row["correction_effect_id"] == plan["entries"][1]["posting_effect_id"])
            movement = next(item for item in rows(runtime, "inventory_movements") if item["id"] == row["physical_movement_id"])
            require(movement["status"] == "Posted" and movement["source_reference"] == plan["id"]
                    and movement["movement_type"] == ("Receipt" if direction == 1 else "Delivery"))
    current = {row["id"]: row for row in rows(runtime, "inventory_cost_layers")}
    for old in old_layers:
        selected = [p for p in expected.portions if p.layer_id == old["id"]]
        direction = -1 if expected.event.kind == "ReverseReturn" else 1
        require(current[old["id"]]["remaining_quantity_scaled"] == old["remaining_quantity_scaled"] + direction * sum(p.quantity_scaled for p in selected))
        require(current[old["id"]]["remaining_value_minor"] == old["remaining_value_minor"] + direction * sum(p.value_minor for p in selected))


def test_independent_actual_two_layer_posted_cycle_binds_each_increment_to_raw_rows(receipt_database: tuple[str, str]) -> None:
    # Call the fixture constructor, creating this test's own tenant; never mutate
    # the module-scoped source fixture used by the mapper's separate cases.
    runtime, source_id, invoice_id = two_layer_source.__wrapped__(receipt_database)
    source = original_vector(runtime, source_id)
    events = (Event("return-12", "Return", 0, quantity_scaled=12), Event("collect-3500", "Collection", 1, amount_minor=3500),
              Event("return-3", "Return", 2, quantity_scaled=3), Event("refund-6000", "Refund", 3, amount_minor=6000),
              Event("refund-7500", "Refund", 4, amount_minor=7500))
    expected = expected_cycle(source, events)
    captures = [capture(runtime)]
    parent: dict[str, Any] | None = None
    for value in expected:
        before, layers, consumed = ledger(runtime), rows(runtime, "inventory_cost_layers"), rows(runtime, "inventory_layer_consumptions")
        event = value.event
        if event.kind == "Return":
            parent = posted(runtime, prepare_return(runtime, source_id, event.quantity_scaled, event.expected_history_version, event.event_id))
            result = parent
        elif event.kind == "Collection":
            complete(runtime, prepare(runtime, invoice_id, event.amount_minor, event.event_id), event.event_id)
            result = None
        else:
            require(parent is not None)
            result = posted(runtime, prepare_refund(runtime, parent, event.amount_minor, event.expected_history_version, event.event_id))
        verify_economics(runtime, source, value, result, before, layers, consumed)
        current = balance(runtime, source_id)
        require((current["outstanding_minor"], current["refund_due_minor"], current["credited_minor"], current["collected_minor"],
                 current["returned_quantity_scaled"], current["history_version"]) ==
                (value.receivable_minor, value.refund_liability_minor, value.total_credit_minor, value.total_collections_minor,
                 value.returned_quantity_scaled, event.expected_history_version + 1))
        captures.append(capture(runtime))
    effects = rows(runtime, "finance_posting_effects")
    posted_ids = {row["entry_id"] for row in effects}
    lines = [row for row in rows(runtime, "finance_entry_lines") if row["entry_id"] in posted_ids]
    require(len(effects) == 12 and len(lines) == 24)
    require(sum(row["debit_minor"] for row in lines) == sum(row["credit_minor"] for row in lines) == 238000)
    require(not rows(runtime, "inventory_valuation_reversals"))
    packet = {"schema_version": "customer-partial-return-posted-cycle-input-v1", "tenant_id": runtime.tenant,
              "source_order_id": source_id, "captures": captures}
    proof = qualify_raw_cycle(packet)
    require((proof["events"], proof["new_actual_posting_effects"], proof["new_actual_posted_lines"]) == (5, 7, 14))
    # The caller must choose a private destination. No public artifact path is
    # inferred and existing originals are never replaced.
    private_output = os.environ.get("RECONFORGE_PARTIAL_CYCLE_PRIVATE_OUTPUT")
    if private_output:
        destination = Path(private_output).resolve()
        require(destination.is_dir())
        with (destination / "native-posted-cycle-original-v1.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(packet, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")


def test_all_four_owned_families_refuse_generic_post_and_generic_full_inverse(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, _invoice_id = create_partial_runtime(receipt_database)
    original_return = original_refund = None
    for version, operation in enumerate(("Return", "Refund", "ReverseRefund", "ReverseReturn")):
        if operation == "Return":
            plan = prepare_return(runtime, source_id, 10, version)
        elif operation == "Refund":
            plan = prepare_refund(runtime, original_return, 3000, version, "family-refund")
        else:
            plan = prepare_reversal(runtime, original_refund if operation == "ReverseRefund" else original_return,
                                    version, "family-" + operation)
        reviewed = phase(runtime, plan, "review", "checker")
        before = retained(runtime)
        with pytest.raises(FinancePostingError), runtime.actor("poster") as (connection, _, actor):
            PostgresFinancePostingRepository(connection, runtime.tenant).post(reviewed["entries"][0]["entry_id"],
                command_id="generic-post-" + operation, expected_validation_digest=reviewed["entries"][0]["validation_digest"],
                reason="No native participant admission", actor=actor)
        unchanged(before, retained(runtime))
        actual = phase(runtime, reviewed, "post", "poster")
        if operation == "Return":
            original_return = actual
        elif operation == "Refund":
            original_refund = actual
        before = retained(runtime)
        with pytest.raises(FinancePostingError), runtime.actor("maker") as (connection, _, actor):
            PostgresFinancePostingRepository(connection, runtime.tenant).prepare_reversal(actual["entries"][0]["posting_effect_id"],
                command_id="generic-inverse-" + operation, entry_number="UNOWNED-" + operation.upper(), period_id="period",
                posting_date="2026-10-14", reason="No owned governed inverse", actor=actor)
        unchanged(before, retained(runtime))


@pytest.mark.parametrize("attack", ["reserved-number-rename", "reference-rename", "extra-native-reference", "extra-native-movement",
                                  "direct-inverse-header", "phase-forgery", "history-update"])
def test_ordinary_app_sql_cannot_detach_or_forge_native_owner_graph(receipt_database: tuple[str, str], attack: str) -> None:
    runtime, source_id, _invoice_id = create_partial_runtime(receipt_database)
    plan = prepare_return(runtime, source_id, 4)
    if attack in {"history-update", "extra-native-movement", "direct-inverse-header"}:
        plan = posted(runtime, plan)
    before = retained(runtime)
    with pytest.raises(psycopg.errors.CheckViolation) as denied, runtime.actor("poster") as (connection, _, _actor):
        if attack == "reserved-number-rename":
            connection.execute("UPDATE reconforge.finance_entries SET entry_number='ESCAPED-NATIVE-NAMESPACE' WHERE tenant_id=%s AND id=%s",
                               (runtime.tenant, plan["entries"][0]["entry_id"]))
        elif attack == "reference-rename":
            connection.execute("UPDATE reconforge.finance_entries SET external_reference='ESCAPED-NATIVE-OWNER' WHERE tenant_id=%s AND id=%s",
                               (runtime.tenant, plan["entries"][0]["entry_id"]))
        elif attack in {"extra-native-reference", "direct-inverse-header"}:
            # A complete ordinary balanced draft isolates native ownership:
            # missing lines or an invalid generic total cannot explain refusal.
            extra = PostgresFinanceCoreRepository(connection, runtime.tenant).create_entry(entry_number="EXTRA-NATIVE-BORROW",
                organization_code="ORG", entity_code="ENTITY", period_id="period", journal_code="SALES", posting_date="2026-10-14",
                description="Balanced ordinary draft with a forged native relationship", workspace="work",
                external_reference=plan["id"] if attack == "extra-native-reference" else "",
                lines=[{"account_code": "AR", "debit": "1.00", "credit": "0.00"},
                       {"account_code": "REVENUE", "debit": "0.00", "credit": "1.00"}], actor_label="poster")
            if attack == "direct-inverse-header":
                connection.execute("UPDATE reconforge.finance_entries SET reverses_posting_id=%s WHERE tenant_id=%s AND id=%s",
                                   (plan["entries"][0]["posting_effect_id"], runtime.tenant, extra["id"]))
        elif attack == "extra-native-movement":
            PostgresInventoryCoreRepository(connection, runtime.tenant).create_movement(movement_number="EXTRA-NATIVE-MOVEMENT",
                movement_type="Receipt", organization_code="ORG", entity_code="ENTITY", period_id="period", movement_date="2026-10-14",
                description="Complete extra physical draft borrowing an owned plan", workspace="work", source_type="Generated",
                source_reference=plan["id"], actor_label="poster", lines=[{"item_code": "ITEM", "quantity": "1", "to_location": "MAIN/STOCK"}])
        elif attack == "phase-forgery":
            connection.execute("UPDATE reconforge.customer_partial_return_plans SET phase=2 WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["id"]))
        else:
            connection.execute("UPDATE reconforge.customer_partial_return_history SET credit_minor=credit_minor+1 WHERE tenant_id=%s AND plan_id=%s",
                               (runtime.tenant, plan["id"]))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    if attack in {"extra-native-reference", "extra-native-movement"}:
        require(denied.value.diag.message_primary == "Extra native rows cannot borrow an existing partial source reference")
    unchanged(before, retained(runtime))


def test_failure_after_first_real_gl_effect_rolls_back_physical_owner_and_all_rows(receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, source_id, _invoice_id = create_partial_runtime(receipt_database)
    reviewed = phase(runtime, prepare_return(runtime, source_id, 4), "review", "checker")
    before = retained(runtime)
    real_post, calls = PostgresFinancePostingRepository.post, []

    def fail_after_effect(self: Any, *args: Any, **kwargs: Any) -> Any:
        value = real_post(self, *args, **kwargs)
        calls.append(value["id"])
        if len(calls) == 1:
            raise RuntimeError("Injected after first actual partial GL effect")
        return value

    with monkeypatch.context() as fault:
        fault.setattr(PostgresFinancePostingRepository, "post", fail_after_effect)
        with pytest.raises(RuntimeError, match="after first actual"):
            phase(runtime, reviewed, "post", "poster")
    require(len(calls) == 1)
    unchanged(before, retained(runtime))
    result = phase(runtime, reviewed, "post", "poster")
    require(result["phase"] == 2 and len(result["entries"]) == 2)


def test_lost_ack_replay_is_exact_then_current_permission_withdrawal_denies_cached_ack(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, _invoice_id = create_partial_runtime(receipt_database)
    reviewed = phase(runtime, prepare_return(runtime, source_id, 4), "review", "checker")
    original = phase(runtime, reviewed, "post", "poster", "lost-partial-post-ack")
    before = retained(runtime)
    require(phase(runtime, reviewed, "post", "poster", "lost-partial-post-ack") == original)
    unchanged(before, retained(runtime))
    # Preserve a stale authenticated principal/actor before durable withdrawal.
    from reconforge.infrastructure.postgres import PostgresTenantBoundary
    from reconforge.platform.common import current_server_principal, server_principal_context

    with runtime.actor("poster") as (_connection, _, cached_actor):
        cached_principal = current_server_principal()
    require(cached_principal is not None)
    with runtime.actor("maker") as (connection, _, actor):
        connection.execute("""UPDATE reconforge.identity_role_permissions SET active=FALSE,revoked_at=now(),revoked_by=%s,
            revocation_reason_code='access_change',lifecycle_version=lifecycle_version+1
            WHERE tenant_id=%s AND permission_name='finance_core.post'""", (actor.user_id, runtime.tenant))
    before = retained(runtime)
    with pytest.raises(FinancePostingError) as denied, PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant,
            workspace_id="work", organization_id="org", legal_entity_id="entity") as connection, server_principal_context(cached_principal):
        PostgresCustomerPartialReturnsRepository(connection, runtime.tenant).post(reviewed["id"], expected_plan_digest=reviewed["plan_digest"],
            command_id="lost-partial-post-ack", reason="Actual partial credit post", actor=cached_actor)
    require(denied.value.code == "operational_actor_denied")
    unchanged(before, retained(runtime))


def test_concurrent_distinct_commands_cannot_reserve_the_same_original_quantity_twice(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, _invoice_id = create_partial_runtime(receipt_database)
    gate = Barrier(2)

    def contender(number: int) -> str:
        try:
            with runtime.actor("maker") as (connection, _, actor):
                connection.execute("SET LOCAL lock_timeout='5s'")
                connection.execute("SET LOCAL statement_timeout='10s'")
                gate.wait(timeout=5)
                PostgresCustomerPartialReturnsRepository(connection, runtime.tenant).prepare(request(source_id, 6),
                    command_id="competing-partial-" + str(number), actor=actor)
            return "reserved"
        except FinancePostingError:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(contender, (1, 2)))
    require(sorted(outcomes) == ["refused", "reserved"])
    require(len(rows(runtime, "customer_partial_return_plans")) == 1 and not rows(runtime, "customer_partial_return_history"))
    require(balance(runtime, source_id)["history_version"] == 0)


def test_read_scope_cannot_be_substituted_and_hidden_tenant_rows_remain_invisible(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, _invoice_id = create_partial_runtime(receipt_database)
    hidden_runtime, hidden_source, _hidden_invoice = create_partial_runtime(receipt_database)
    hidden_plan = prepare_return(hidden_runtime, hidden_source, 4)
    plan = prepare_return(runtime, source_id, 4)
    before = retained(runtime)
    with pytest.raises(FinancePostingError), runtime.actor("maker") as (connection, _, actor):
        PostgresCustomerPartialReturnsRepository(connection, runtime.tenant).balance(source_id, {**SCOPE, "workspace_id": "hidden-workspace"}, actor=actor)
    unchanged(before, retained(runtime))
    with runtime.actor("maker") as (connection, _, _actor):
        require(connection.execute("SELECT count(*) n FROM reconforge.customer_partial_return_plans WHERE tenant_id=%s AND id=%s",
                                   (hidden_runtime.tenant, hidden_plan["id"])).fetchone()["n"] == 0)
        require(connection.execute("SELECT id FROM reconforge.customer_partial_return_plans WHERE tenant_id=%s AND id=%s", (runtime.tenant, plan["id"])).fetchone() is not None)


def reviewed_resale(runtime: ReceiptRuntime, number: str, quantity: str) -> dict[str, Any]:
    sale = create_reserved_order(runtime, number, quantity)
    sale = execute(runtime, sale, "prepare-issue", "maker", {"posting_date": "2026-10-14", "period_id": "period", "policy_code": "FIFO"})
    return execute(runtime, sale, "review-issue", "checker")


def test_legitimate_prior_consumption_does_not_falsely_block_owned_return_reversal(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, _invoice_id = two_layer_source.__wrapped__(receipt_database)
    resale = reviewed_resale(runtime, "C-PRIOR-CONSUMPTION", "3")
    execute(runtime, resale, "deliver", "poster")
    before_layers = rows(runtime, "inventory_cost_layers")
    returned = posted(runtime, prepare_return(runtime, source_id, 12))
    restoration_rows = [row for row in rows(runtime, "customer_partial_return_restorations") if row["plan_id"] == returned["id"]]
    require(len(restoration_rows) == 2 and all(type(row["consumption_count_at_restore"]) is int for row in restoration_rows))
    inverse = posted(runtime, prepare_reversal(runtime, returned, 1, "C-REVERSE-AFTER-PRIOR-CONSUMPTION"))
    require(inverse["operation"] == "ReverseReturn" and balance(runtime, source_id)["returned_quantity_scaled"] == 0)
    old = {row["id"]: (row["remaining_quantity_scaled"], row["remaining_value_minor"]) for row in before_layers}
    new = {row["id"]: (row["remaining_quantity_scaled"], row["remaining_value_minor"]) for row in rows(runtime, "inventory_cost_layers")}
    unchanged(old, new)


def test_transaction_started_before_return_but_consuming_after_layer_wait_blocks_reversal(receipt_database: tuple[str, str]) -> None:
    runtime, source_id, _invoice_id = two_layer_source.__wrapped__(receipt_database)
    reviewed = phase(runtime, prepare_return(runtime, source_id, 12), "review", "checker")
    started: Queue[tuple[int, Any]] = Queue()
    prepared_sale: Queue[dict[str, Any]] = Queue()
    continue_delivery = ThreadEvent()

    def old_transaction() -> dict[str, Any]:
        with runtime.actor("poster") as (connection, _, actor):
            connection.execute("SET LOCAL lock_timeout='10s'")
            connection.execute("SET LOCAL statement_timeout='20s'")
            native = connection.execute("SELECT pg_backend_pid() pid,transaction_timestamp() started").fetchone()
            started.put((native["pid"], native["started"]))
            require(continue_delivery.wait())
            resale = prepared_sale.get(timeout=5)
            return repository(connection, runtime).act(resale["id"], "deliver", expected_version=resale["row_version"],
                command_id="C-ACTUAL-OLDER-TX-DELIVERY", reason="Real later consumption with an older transaction timestamp",
                parameters={}, actor=actor)

    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(old_transaction)
        try:
            waiter, old_timestamp = started.get(timeout=8)
            returned = phase(runtime, reviewed, "post", "poster")
            post_event = next(row for row in rows(runtime, "customer_partial_return_events")
                              if row["plan_id"] == returned["id"] and row["operation"] == "post")
            from datetime import datetime

            require(old_timestamp < datetime.fromisoformat(post_event["created_at"]))
            # Prepare/review against the actual post-return FIFO version.
            # Preparing before the return would correctly fail the existing
            # frozen-cost version guard and would not test later consumption.
            resale = reviewed_resale(runtime, "C-OLD-TRANSACTION-LATER-CONSUMPTION", "1")
            prepared_sale.put(resale)
            target_layer = resale["issue_plan"]["allocations"][0]["cost_layer_id"]
            with runtime.actor("maker") as (holder, _, _actor):
                holder.execute("SELECT id FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s FOR UPDATE", (runtime.tenant, target_layer))
                holder_pid = holder.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
                continue_delivery.set()
                with psycopg.connect(runtime.admin_dsn, autocommit=True, connect_timeout=5) as observer:
                    deadline = time.monotonic() + 8
                    while holder_pid not in observer.execute("SELECT pg_blocking_pids(%s)", (waiter,)).fetchone()[0]:
                        require(time.monotonic() < deadline and not future.done())
                        time.sleep(.025)
                require(not future.done())
            delivered = future.result(timeout=25)
        finally:
            continue_delivery.set()
    require(delivered["status"] == "Delivered")
    before = retained(runtime)
    with pytest.raises(FinancePostingError):
        prepare_reversal(runtime, returned, 1, "C-DENY-POST-RESTORE-CONSUMPTION")
    unchanged(before, retained(runtime))


@pytest.mark.parametrize("forgery", ["refund-parent", "cross-source-return"])
def test_sql_close_rejects_forged_refund_parent_after_repository_checks(receipt_database: tuple[str, str],
                                                                     monkeypatch: pytest.MonkeyPatch, forgery: str) -> None:
    runtime, source_id, _invoice_id = create_partial_runtime(receipt_database)
    returned = posted(runtime, prepare_return(runtime, source_id, 10))
    version = 1
    if forgery == "refund-parent":
        invalid_parent = posted(runtime, prepare_refund(runtime, returned, 3000, 1, "C-PRIOR-REFUND-PARENT"))
        version = 2
    else:
        # A second genuine posted Return in this SAME tenant makes the FK and
        # visibility valid while source affinity is wrong. A hidden foreign-
        # tenant row would only test generic RLS/FK rejection.
        sale = reviewed_resale(runtime, "C-SECOND-SOURCE-PARENT", "5")
        sale = execute(runtime, sale, "deliver", "poster")
        invoice_args = SalesInvoicePreparation("C-SECOND-SOURCE-INVOICE", "2026-10-14", "2026-10-31", "SALES", "period",
                                              "AR", "REVENUE", "Second genuine source for affinity refusal").payload()
        invoice_args.pop("reason")
        sale = execute(runtime, sale, "prepare-invoice", "maker", invoice_args)
        sale = execute(runtime, sale, "review-invoice", "checker")
        sale = execute(runtime, sale, "invoice", "poster")
        invalid_parent = posted(runtime, prepare_return(runtime, sale["id"], 5, 0, "C-SECOND-SOURCE-RETURN"))
    before = retained(runtime)
    real_save = PostgresCustomerPartialReturnsRepository._save

    def forged_persist(self: Any, payload: dict[str, Any], actor: Any) -> None:
        require(payload["operation"] == "Refund")
        payload["original_id"] = invalid_parent["id"]
        # The real _save recomputes the digest and writes real audit/outbox/
        # plan rows under the ordinary app role. Repository parent admission
        # has already succeeded, so deferred SQL ownership must reject this.
        real_save(self, payload, actor)

    with monkeypatch.context() as adversary:
        adversary.setattr(PostgresCustomerPartialReturnsRepository, "_save", forged_persist)
        with pytest.raises(psycopg.errors.CheckViolation) as denied:
            prepare_refund(runtime, returned, 1000, version, "C-FORGED-REFUND-PARENT")
    require(denied.value.diag.constraint_name == "customer_partial_return_owner")
    unchanged(before, retained(runtime))
