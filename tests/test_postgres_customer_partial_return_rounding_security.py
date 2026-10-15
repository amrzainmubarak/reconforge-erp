"""Independent ordinary-app counterexamples for remaining-original allocation.

Collection and pure models do not qualify these tests as executed. Every test
uses native originals and retains all 79 financial tables around a refusal.
Assertions expose constant diagnostics instead of private PostgreSQL row text.
"""
from __future__ import annotations

import json
import os
import stat
from collections import defaultdict
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql

from reconforge.domain.customer_partial_return_commands import (
    CustomerPartialRefundPreparation,
    CustomerPartialReversePreparation,
)
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_customer_partial_returns import PostgresCustomerPartialReturnsRepository
from reconforge.platform.common import current_server_principal, server_principal_context
from tests.customer_partial_return_posted_cycle_oracle import TABLES, decode_row, require
from tests.test_postgres_customer_partial_return_rounding import (
    create_remainder_runtime,
    current_v2,
    phase_v2,
    post_v2,
    prepare_v2,
)
from tests.test_postgres_customer_partial_returns import create_partial_runtime, phase, prepare_return, request
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database

_ = receipt_database
ROUNDING_TABLES = (*TABLES, "customer_partial_return_allocation_witnesses")


def capture_rounding(runtime: ReceiptRuntime) -> dict[str, tuple[str, ...]]:
    with runtime.actor("maker") as (connection, _, _actor):
        return {name: tuple(row["original"] for row in connection.execute(
            sql.SQL('SELECT to_jsonb(r)::text original FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text COLLATE "C"')
            .format(sql.Identifier(name)), (runtime.tenant,)).fetchall()) for name in ROUNDING_TABLES}


def check_cause(error: BaseException) -> psycopg.errors.CheckViolation:
    """Inspect the owner's exact cause without accepting an unrelated refusal."""
    cause: BaseException | None = error
    for _ in range(8):
        if isinstance(cause, psycopg.errors.CheckViolation):
            return cause
        cause = cause.__cause__ if cause is not None else None
    raise AssertionError("The expected native CHECK cause was not retained.")


def test_zero_plan_row_check_requires_explicit_v2_schema_and_nonnull_literal_policy(
    receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, source = create_remainder_runtime(receipt_database, zero=True)
    control = prepare_v2(runtime, source, 1, 0, "C-ZERO-CHECK-CONTROL")
    require(control["amount_minor"] == 0 and control["entries"] == [])
    phase_v2(runtime, control, "cancel", "checker")
    with runtime.actor("maker") as (connection, _, _actor):
        constraints = connection.execute("""SELECT conname FROM pg_constraint
            WHERE conrelid='reconforge.customer_partial_return_plans'::regclass AND contype='c'
            AND pg_get_constraintdef(oid) LIKE '%%allocation_policy%%'
            AND pg_get_constraintdef(oid) LIKE '%%credit_minor%%'""").fetchall()
    require(len(constraints) == 1)
    expected_constraint = constraints[0]["conname"]
    real_save = PostgresCustomerPartialReturnsRepository._save
    for attack in ("missing-policy", "null-policy", "invalid-policy", "missing-schema", "fake-v1"):
        before = capture_rounding(runtime)

        def malformed(self: Any, payload: dict[str, Any], actor: Any, attack: str = attack) -> None:
            require(payload["amount_minor"] == 0 and payload["entries"] == [])
            if attack == "missing-policy":
                payload.pop("allocation_policy")
            elif attack == "null-policy":
                payload["allocation_policy"] = None
            elif attack == "invalid-policy":
                payload["allocation_policy"] = "unapproved-current-policy"
            elif attack == "missing-schema":
                payload.pop("schema_version")
            else:
                payload["schema_version"] = "customer-partial-return-v1"
            real_save(self, payload, actor)

        with monkeypatch.context() as adversary:
            adversary.setattr(PostgresCustomerPartialReturnsRepository, "_save", malformed)
            with pytest.raises(FinancePostingError) as denied, runtime.actor("maker") as (connection, _, actor):
                owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2)
                owner.prepare(request(source, 1, 0), command_id="C-ZERO-CHECK-" + attack, actor=actor)
        require(check_cause(denied.value).diag.constraint_name == expected_constraint)
        require(capture_rounding(runtime) == before)


def test_same_zero_rounding_result_cannot_hide_a_forged_original_before_value(
    receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, source = create_remainder_runtime(receipt_database, zero=True)
    control = prepare_v2(runtime, source, 1, 0, "C-ZERO-WITNESS-CONTROL")
    phase_v2(runtime, control, "cancel", "checker")
    before = capture_rounding(runtime)
    real_save = PostgresCustomerPartialReturnsRepository._save

    def forged(self: Any, payload: dict[str, Any], actor: Any) -> None:
        require(payload["cogs_restored_minor"] == 0 and payload["domain_plan"]["portions"][0]["before_value_minor"] == 1)
        # Both 1/3 and forged 0/3 round to zero. Equality of the monetary
        # result cannot substitute for exact immutable original-prefix facts.
        payload["domain_plan"]["portions"][0]["before_value_minor"] = 0
        real_save(self, payload, actor)

    with monkeypatch.context() as adversary:
        adversary.setattr(PostgresCustomerPartialReturnsRepository, "_save", forged)
        with pytest.raises(psycopg.errors.CheckViolation) as denied, runtime.actor("maker") as (connection, _, actor):
            owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2)
            owner.prepare(request(source, 1, 0), command_id="C-FORGED-ZERO-BEFORE", actor=actor)
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    require(denied.value.diag.constraint_name == "customer_partial_return_owner")
    require(denied.value.diag.message_primary == "V2 prepared allocation must retain its exact original prefix")
    require(capture_rounding(runtime) == before)


def test_version_two_cannot_upgrade_a_source_already_born_under_version_one(receipt_database: tuple[str, str]) -> None:
    runtime, source = create_remainder_runtime(receipt_database)
    # Full original quantity/cost is a valid v1 control, with no fractional cut.
    legacy = prepare_return(runtime, source, 3, 0, "C-LEGACY-BIRTH")
    require(legacy["schema_version"] == "customer-partial-return-v1" and legacy["cogs_restored_minor"] == 1001)
    phase(runtime, legacy, "cancel", "checker")
    before = capture_rounding(runtime)
    with pytest.raises(FinancePostingError) as denied, runtime.actor("maker") as (connection, _, actor):
        PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2).prepare(
            request(source, 3, 0), command_id="C-NO-SILENT-UPGRADE", actor=actor)
    require(denied.value.code == "customer_partial_return_protocol_conflict")
    require(capture_rounding(runtime) == before)


def test_posted_zero_witness_cannot_authorize_a_new_unowned_zero_layer_change(receipt_database: tuple[str, str]) -> None:
    runtime, source = create_remainder_runtime(receipt_database, zero=True)
    plan = post_v2(runtime, prepare_v2(runtime, source, 1, 0, "C-POSTED-ZERO"))
    require(plan["phase"] == 2 and plan["entries"] == [])
    before = capture_rounding(runtime)
    with runtime.actor("poster") as (connection, _, _actor):
        rows = connection.execute("""SELECT r.cost_layer_id,l.remaining_quantity_scaled,l.remaining_value_minor
            FROM reconforge.customer_partial_return_restorations r JOIN reconforge.inventory_cost_layers l
            ON(l.tenant_id,l.id)=(r.tenant_id,r.cost_layer_id)
            WHERE r.tenant_id=%s AND r.plan_id=%s""", (runtime.tenant, plan["id"])).fetchall()
    require(len(rows) == 1 and rows[0]["remaining_quantity_scaled"] == 1 and rows[0]["remaining_value_minor"] == 0)
    with pytest.raises(psycopg.errors.CheckViolation) as denied, runtime.actor("poster") as (connection, _, actor):
        connection.execute("SELECT set_config('app.customer_partial_return_actor_id',%s,true)", (actor.user_id,))
        connection.execute("""UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=remaining_quantity_scaled+1
            WHERE tenant_id=%s AND id=%s""", (runtime.tenant, rows[0]["cost_layer_id"]))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    require(denied.value.diag.constraint_name == "customer_partial_return_owner")
    require(denied.value.diag.message_primary == "A zero-value physical layer requires its exact visible native allocation witness")
    require(capture_rounding(runtime) == before)


def test_supplemental_witnesses_inherit_all_four_parent_scope_boundaries_and_are_immutable(receipt_database: tuple[str, str]) -> None:
    runtime, source = create_remainder_runtime(receipt_database, zero=True)
    plan = post_v2(runtime, prepare_v2(runtime, source, 1, 0, "C-WITNESS-RLS"))
    before = capture_rounding(runtime)
    require(len(before["customer_partial_return_allocation_witnesses"]) == 1)
    for scope_key in ("tenant_id", "workspace_id", "organization_id", "legal_entity_id"):
        with runtime.actor("maker") as (connection, _, _actor):
            query = "SELECT count(*) n FROM reconforge.customer_partial_return_allocation_witnesses WHERE tenant_id=%s AND plan_id=%s"
            require(connection.execute(query, (runtime.tenant, plan["id"])).fetchone()["n"] == 1)
            connection.execute("SELECT set_config(%s,%s,true)", ("app." + scope_key, "hidden-sibling-scope"))
            require(connection.execute(query, (runtime.tenant, plan["id"])).fetchone()["n"] == 0)
    for operation in ("UPDATE", "DELETE"):
        with pytest.raises(psycopg.errors.CheckViolation) as denied, runtime.actor("poster") as (connection, _, _actor):
            if operation == "UPDATE":
                connection.execute("""UPDATE reconforge.customer_partial_return_allocation_witnesses SET before_value_minor=0
                    WHERE tenant_id=%s AND plan_id=%s""", (runtime.tenant, plan["id"]))
            else:
                connection.execute("DELETE FROM reconforge.customer_partial_return_allocation_witnesses WHERE tenant_id=%s AND plan_id=%s",
                                   (runtime.tenant, plan["id"]))
        require(denied.value.diag.constraint_name == "customer_partial_return_owner")
        require(denied.value.diag.message_primary == "Original allocation witness is immutable")
        require(capture_rounding(runtime) == before)


def test_zero_effect_cached_ack_rechecks_current_posting_authority(receipt_database: tuple[str, str]) -> None:
    runtime, source = create_remainder_runtime(receipt_database, zero=True)
    reviewed = phase_v2(runtime, prepare_v2(runtime, source, 1, 0, "C-ZERO-AUTHORITY"), "review", "checker")
    actual = phase_v2(runtime, reviewed, "post", "poster")
    require(actual["phase"] == 2 and actual["entries"] == [])
    before = capture_rounding(runtime)
    require(phase_v2(runtime, reviewed, "post", "poster") == actual)
    require(capture_rounding(runtime) == before)
    with runtime.actor("poster") as (_connection, _, cached_actor):
        principal = current_server_principal()
    if principal is None:
        raise AssertionError("The authenticated native poster is required.")
    with runtime.actor("maker") as (connection, _, actor):
        connection.execute("""UPDATE reconforge.identity_role_permissions SET active=FALSE,revoked_at=now(),revoked_by=%s,
            revocation_reason_code='access_change',lifecycle_version=lifecycle_version+1
            WHERE tenant_id=%s AND permission_name='finance_core.post'""", (actor.user_id, runtime.tenant))
    before = capture_rounding(runtime)
    with pytest.raises(FinancePostingError) as denied, PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant,
            workspace_id="work", organization_id="org", legal_entity_id="entity") as connection, server_principal_context(principal):
        PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2).post(reviewed["id"],
            expected_plan_digest=reviewed["plan_digest"], command_id=reviewed["id"] + ":post",
            reason="Actual remaining-value post", actor=cached_actor)
    require(denied.value.code == "operational_actor_denied")
    require(capture_rounding(runtime) == before)


def test_actual_v2_split_refunds_lost_ack_and_refund_inverse_match_independent_raw_gl(
    receipt_database: tuple[str, str],
) -> None:
    runtime, source, _invoice = create_partial_runtime(receipt_database, paid=10000)
    captures = [capture_rounding(runtime)]
    stock = [row for row in map(decode_row, captures[0]["stock_sales_orders"]) if row["id"] == source]
    invoices = [row for row in map(decode_row, captures[0]["ar_invoices"]) if row["id"] == _invoice]
    require(len(stock) == len(invoices) == 1 and stock[0]["quantity_scaled"] == 10
            and stock[0]["issue_plan"]["total_cost_minor"] == 12000 and invoices[0]["total_minor"] == 45000)
    require(sum(row["amount_minor"] for row in map(decode_row, captures[0]["ar_receipt_allocations"])
                if row["invoice_id"] == _invoice) == 10000)
    # Hand-derived changes to debit-minus-credit balances, not production math.
    vectors = (
        {"INVENTORY": 9600, "COGS": -9600, "REVENUE": 36000, "AR": -35000, "REFUND": -1000},
        {"INVENTORY": 2400, "COGS": -2400, "REVENUE": 9000, "REFUND": -9000},
        {"REFUND": 3000, "CASH": -3000}, {"REFUND": 7000, "CASH": -7000},
        {"REFUND": -7000, "CASH": 7000}, {"REFUND": 7000, "CASH": -7000},
    )
    expected_effects, expected_lines = (2, 2, 1, 1, 1, 1), (5, 4, 2, 2, 2, 2)
    expected_turnover = (45600, 11400, 3000, 7000, 7000, 7000)
    expected_due = (1000, 10000, 7000, 0, 7000, 0)
    second_return = previous_refund = None
    all_effects: set[str] = set()
    all_entries: set[str] = set()
    turnover = 0
    for index in range(6):
        if index < 2:
            plan = prepare_v2(runtime, source, 8 if index == 0 else 2, index, "C-V2-SPLIT-RETURN-" + str(index))
        else:
            with runtime.actor("maker") as (connection, _, actor):
                owner = PostgresCustomerPartialReturnsRepository(connection, runtime.tenant, protocol_version=2)
                if index == 4:
                    if previous_refund is None:
                        raise AssertionError("The exact posted second refund is required.")
                    plan = owner.prepare_reversal(CustomerPartialReversePreparation(previous_refund["id"], "period", "2026-10-14",
                        "Reverse the exact second governed refund", index), command_id="C-V2-SPLIT-REFUND-INVERSE", actor=actor)
                else:
                    if second_return is None:
                        raise AssertionError("The exact posted second return is required.")
                    plan = owner.prepare_refund(CustomerPartialRefundPreparation(second_return["id"], 3000 if index == 2 else 7000,
                        "period", "2026-10-14", "Actual split original cash refund", index),
                        command_id="C-V2-SPLIT-REFUND-" + str(index), actor=actor)
        posted = post_v2(runtime, plan)
        if index == 1:
            second_return = posted
        if index == 3:
            previous_refund = posted
            # Simulate a lost response by discarding it, then resubmit exactly
            # the retained reviewed command. Every original table stays exact.
            retained = capture_rounding(runtime)
            require(phase_v2(runtime, plan, "post", "poster") == posted)
            require(capture_rounding(runtime) == retained)
        after = capture_rounding(runtime)
        before = captures[-1]
        captures.append(after)
        old_effects = {decode_row(raw)["id"] for raw in before["finance_posting_effects"]}
        effects = [decode_row(raw) for raw in after["finance_posting_effects"] if decode_row(raw)["id"] not in old_effects]
        require(len(effects) == expected_effects[index])
        entry_ids = {effect["entry_id"] for effect in effects}
        require(entry_ids == {part["entry_id"] for part in posted["entries"]})
        entries = [decode_row(raw) for raw in after["finance_entries"] if decode_row(raw)["id"] in entry_ids]
        require(len(entries) == len(entry_ids) and all(entry["status"] == "Validated" for entry in entries))
        lines = [decode_row(raw) for raw in after["finance_entry_lines"] if decode_row(raw)["entry_id"] in entry_ids]
        require(len(lines) == expected_lines[index])
        accounts = {row["id"]: row["account_code"] for row in map(decode_row, after["finance_accounts"])}
        delta: defaultdict[str, int] = defaultdict(int)
        for entry_id in entry_ids:
            linked = [line for line in lines if line["entry_id"] == entry_id]
            require(sum(line["debit_minor"] for line in linked) == sum(line["credit_minor"] for line in linked) > 0)
        for line in lines:
            require(type(line["debit_minor"]) is int and type(line["credit_minor"]) is int
                    and min(line["debit_minor"], line["credit_minor"]) == 0 < max(line["debit_minor"], line["credit_minor"]))
            delta[accounts[line["account_id"]]] += line["debit_minor"] - line["credit_minor"]
        require({key: value for key, value in delta.items() if value} == vectors[index])
        debit, credit = sum(line["debit_minor"] for line in lines), sum(line["credit_minor"] for line in lines)
        require(debit == credit == expected_turnover[index])
        turnover += debit
        all_effects.update(effect["id"] for effect in effects)
        all_entries.update(entry_ids)
        require(set(before["finance_posting_effects"]).issubset(after["finance_posting_effects"]))
        require(after["inventory_layer_consumptions"] == captures[0]["inventory_layer_consumptions"])
        history = sorted(map(decode_row, after["customer_partial_return_history"]), key=lambda row: row["sequence"])
        require(len(history) == index + 1 and history[-1]["plan_id"] == posted["id"])
        require(history[-1]["kind"] == ("Return" if index < 2 else "ReverseRefund" if index == 4 else "Refund"))
        state = current_v2(runtime, source)
        require(state["history_version"] == index + 1 and state["refund_due_minor"] == expected_due[index]
                and state["outstanding_minor"] == 0)
    require(len(all_effects) == len(all_entries) == 8 and turnover == 81000)
    require(sum(1 for raw in captures[-1]["finance_entry_lines"] if decode_row(raw)["entry_id"] in all_entries) == 17)
    destination = os.environ.get("RECONFORGE_PARTIAL_REMAINDER_PRIVATE_OUTPUT")
    if destination:
        root = Path(destination)
        require(root.is_absolute() and ".." not in root.parts and root.is_dir())
        for member in (root, *root.parents):
            metadata = member.lstat()
            require(not member.is_symlink() and not (getattr(metadata, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))
        packet = {"schema_version": "customer-partial-return-remainder-native-refunds-v1", "tenant_id": runtime.tenant,
                  "source_order_id": source, "captures": captures}
        with (root / "native-v2-refund-posted-cycle-original-v1.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(packet, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
