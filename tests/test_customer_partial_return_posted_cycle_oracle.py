"""Independent arithmetic/adversarial vectors; native row binding is separate."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from typing import Any

import pytest

from tests.customer_partial_return_posted_cycle_oracle import (
    TABLES,
    Consumption,
    CycleRefusal,
    Event,
    OriginalSale,
    decode_row,
    expected_cycle,
    integer,
    posted_ledger_totals,
    prefix_portions,
    qualify_raw_cycle,
    verify_audit_only_transition,
    verify_posted_gl_amount_delta,
    verify_raw_observations,
    verify_raw_restore,
)


def original(*, collected: int = 10000, precision: int = 0) -> OriginalSale:
    return OriginalSale(precision, 15, 67500, collected, "USD", 2, (
        Consumption(1, "old-first", "z-earlier-layer", 10, 12000),
        Consumption(2, "old-second", "a-later-layer", 5, 10000),
    ))


def test_two_posted_portions_later_collection_and_refund_installments_have_independent_effects() -> None:
    values = expected_cycle(original(), (
        Event("return-one", "Return", 0, quantity_scaled=12),
        Event("later-collection", "Collection", 1, amount_minor=3500),
        Event("return-two", "Return", 2, quantity_scaled=3),
        Event("refund-one", "Refund", 3, amount_minor=6000),
        Event("refund-two", "Refund", 4, amount_minor=7500),
    ))
    assert [(v.returned_quantity_scaled, v.total_credit_minor, v.total_collections_minor,
             v.total_refunds_minor, v.receivable_minor, v.refund_liability_minor) for v in values] == [
        (12, 54000, 10000, 0, 3500, 0), (12, 54000, 13500, 0, 0, 0),
        (15, 67500, 13500, 0, 0, 13500), (15, 67500, 13500, 6000, 0, 7500),
        (15, 67500, 13500, 13500, 0, 0),
    ]
    assert dict(values[0].account_deltas) == {"AR": -54000, "REVENUE": 54000, "INVENTORY": 16000, "COGS": -16000}
    assert dict(values[2].account_deltas) == {"REFUND": -13500, "REVENUE": 13500, "INVENTORY": 6000, "COGS": -6000}
    assert [(p.layer_id, p.offset_quantity_scaled, p.quantity_scaled, p.value_minor) for p in values[0].portions] == [
        ("z-earlier-layer", 0, 10, 12000), ("a-later-layer", 0, 2, 4000)]
    assert [(p.layer_id, p.offset_quantity_scaled, p.quantity_scaled, p.value_minor) for p in values[2].portions] == [
        ("a-later-layer", 2, 3, 6000)]


def test_governed_last_operation_reversals_restore_prior_ar_cash_liability_and_original_prefix() -> None:
    values = expected_cycle(original(), (
        Event("r1", "Return", 0, quantity_scaled=12),
        Event("c1", "Collection", 1, amount_minor=3500),
        Event("r2", "Return", 2, quantity_scaled=3),
        Event("f1", "Refund", 3, amount_minor=13500),
        Event("undo-f1", "ReverseRefund", 4, original_event_id="f1"),
        Event("undo-r2", "ReverseReturn", 5, original_event_id="r2"),
        Event("undo-c1", "ReverseCollection", 6, original_event_id="c1"),
        Event("undo-r1", "ReverseReturn", 7, original_event_id="r1"),
    ))
    assert values[-1].returned_quantity_scaled == values[-1].total_credit_minor == values[-1].total_refunds_minor == 0
    assert values[-1].total_collections_minor == 10000 and values[-1].receivable_minor == 57500
    assert values[-1].refund_liability_minor == 0
    assert dict(values[5].account_deltas) == {"REFUND": 13500, "REVENUE": -13500, "INVENTORY": -6000, "COGS": 6000}
    assert sum(amount for v in values for _account, amount in v.account_deltas) == 0
    for account in ("AR", "REVENUE", "INVENTORY", "COGS", "REFUND", "CASH"):
        assert sum(dict(v.account_deltas).get(account, 0) for v in values) == 0


@pytest.mark.parametrize(("collected", "quantity", "credit", "ar_release", "liability", "cost"), [
    (0, 15, 67500, 67500, 0, 22000),
    (10000, 12, 54000, 54000, 0, 16000),
    (60000, 12, 54000, 7500, 46500, 16000),
    (67500, 12, 54000, 0, 54000, 16000),
    (10000, 15, 67500, 57500, 10000, 22000),
    (0, 3, 13500, 13500, 0, 3600),
    (60000, 3, 13500, 7500, 6000, 3600),
])
def test_seven_hand_calculated_integer_fraction_vectors(collected: int, quantity: int, credit: int,
                                                        ar_release: int, liability: int, cost: int) -> None:
    source = original(collected=collected)
    value = expected_cycle(source, (Event("r", "Return", 0, quantity_scaled=quantity),))[0]
    assert value.total_credit_minor == credit == Fraction(67500 * quantity, 15)
    assert value.refund_liability_minor == liability
    assert dict(value.account_deltas).get("AR", 0) == -ar_release
    assert dict(value.account_deltas)["INVENTORY"] == cost


@pytest.mark.parametrize("precision", [0, 1, 3, 6])
def test_captured_quantity_precision_does_not_change_scaled_ratio_or_select_layer_uuid_order(precision: int) -> None:
    value = expected_cycle(original(precision=precision), (Event("r", "Return", 0, quantity_scaled=12),))[0]
    assert value.total_credit_minor == 54000
    assert [(p.layer_id, p.quantity_scaled) for p in value.portions] == [("z-earlier-layer", 10), ("a-later-layer", 2)]


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", None, -1, 9_000_000_000_000_000_001])
def test_no_boolean_float_coercion_missing_or_unbounded_money(bad: object) -> None:
    with pytest.raises(CycleRefusal):
        integer(bad)


@pytest.mark.parametrize("events", [
    (Event("r", "Return", 0, quantity_scaled=16),),
    (Event("c", "Collection", 0, amount_minor=57501),),
    (Event("f", "Refund", 0, amount_minor=1),),
    (Event("r", "Return", 1, quantity_scaled=12),),
    (Event("r", "Return", 0, quantity_scaled=12), Event("r", "Return", 1, quantity_scaled=1)),
    (Event("r", "Return", 0, quantity_scaled=12), Event("c", "Collection", 1, amount_minor=3500),
     Event("reverse", "ReverseReturn", 2, original_event_id="r")),
    (Event("r", "Return", 0, quantity_scaled=12), Event("reverse", "ReverseRefund", 1, original_event_id="r")),
    (Event("r", "Return", 0, quantity_scaled=12), Event("reverse", "ReverseReturn", 1, original_event_id="other")),
])
def test_excess_stale_duplicate_mismatched_or_nonlast_operations_refuse(events: tuple[Event, ...]) -> None:
    with pytest.raises(CycleRefusal):
        expected_cycle(original(), events)


def test_fractional_original_cost_remainder_is_refused_without_implicit_rounding() -> None:
    source = OriginalSale(1, 3, 300, 0, "BHD", 3, (Consumption(1, "consumption", "layer", 3, 100),))
    with pytest.raises(CycleRefusal):
        prefix_portions(source, 0, 1)
    assert expected_cycle(source, (Event("full", "Return", 0, quantity_scaled=3),))[0].total_credit_minor == 300


def test_original_consumption_position_and_exact_membership_are_required() -> None:
    source = original()
    for rows in (tuple(reversed(source.consumptions)), (source.consumptions[0],),
                 (source.consumptions[0], replace(source.consumptions[1], layer_id="z-earlier-layer"))):
        with pytest.raises(CycleRefusal):
            replace(source, consumptions=rows)


def ledger_vector() -> tuple[dict[str, tuple[dict[str, Any], ...]], dict[str, tuple[dict[str, Any], ...]], dict[str, str]]:
    """Explicit independent row vector; no production snapshot/proposal builder."""
    accounts = {role: "account-" + role for role in ("AR", "REVENUE", "INVENTORY", "COGS", "REFUND", "CASH")}
    original_header = {"id": "old-entry", "status": "Validated", "currency_code": "USD", "currency_precision": 2,
                       "total_debit_minor": 67500, "total_credit_minor": 67500}
    before = {"finance_posting_effects": ({"id": "old-effect", "entry_id": "old-entry"},),
              "finance_entries": (original_header,),
              "finance_entry_lines": (
                  {"id": "old-ar", "entry_id": "old-entry", "line_number": 1, "account_id": accounts["AR"], "debit_minor": 67500, "credit_minor": 0},
                  {"id": "old-revenue", "entry_id": "old-entry", "line_number": 2, "account_id": accounts["REVENUE"], "debit_minor": 0, "credit_minor": 67500})}
    after = {"finance_posting_effects": before["finance_posting_effects"] + (
                {"id": "new-credit-effect", "entry_id": "new-credit"}, {"id": "new-cost-effect", "entry_id": "new-cost"}),
             "finance_entries": before["finance_entries"] + (
                 {**original_header, "id": "new-credit", "total_debit_minor": 54000, "total_credit_minor": 54000},
                 {**original_header, "id": "new-cost", "total_debit_minor": 16000, "total_credit_minor": 16000}),
             "finance_entry_lines": before["finance_entry_lines"] + (
                 {"id": "new-revenue", "entry_id": "new-credit", "line_number": 1, "account_id": accounts["REVENUE"], "debit_minor": 54000, "credit_minor": 0},
                 {"id": "new-ar", "entry_id": "new-credit", "line_number": 2, "account_id": accounts["AR"], "debit_minor": 0, "credit_minor": 54000},
                 {"id": "new-inventory", "entry_id": "new-cost", "line_number": 1, "account_id": accounts["INVENTORY"], "debit_minor": 16000, "credit_minor": 0},
                 {"id": "new-cogs", "entry_id": "new-cost", "line_number": 2, "account_id": accounts["COGS"], "debit_minor": 0, "credit_minor": 16000})}
    return deepcopy(before), deepcopy(after), accounts


def test_gl_row_membership_requires_two_actual_posted_corrections_and_four_exact_lines() -> None:
    before, after, accounts = ledger_vector()
    expected = expected_cycle(original(), (Event("r", "Return", 0, quantity_scaled=12),))[0]
    result = verify_posted_gl_amount_delta(original(), expected, before, after, accounts)
    assert (result["posting_effects"], result["posted_entries"], result["posted_lines"]) == (2, 2, 4)
    assert result["unposted_proposal_accepted_as_posting"] is False


@pytest.mark.parametrize("attack", [
    "unposted", "missing-cost", "orphan-effect", "duplicate-effect", "original-effect-changed",
    "original-header-changed", "original-line-changed", "extra-original-line", "unvalidated", "currency",
    "precision-bool", "balanced-amount-tamper", "extra-offsetting-lines", "duplicate-line-id",
    "line-order", "header-total", "boolean-money", "float-money", "unknown-account", "both-sides",
])
def test_gl_oracle_refuses_balanced_tampering_and_proposal_as_posting(attack: str) -> None:
    before, after, accounts = ledger_vector()
    effects, entries, lines = (list(after[name]) for name in ("finance_posting_effects", "finance_entries", "finance_entry_lines"))
    if attack == "unposted":
        effects = effects[:1]
    elif attack == "missing-cost":
        effects.pop()
    elif attack == "orphan-effect":
        effects[-1]["entry_id"] = "absent"
    elif attack == "duplicate-effect":
        effects.append({"id": "extra-effect", "entry_id": "new-credit"})
    elif attack == "original-effect-changed":
        effects[0]["entry_id"] = "new-credit"
    elif attack == "original-header-changed":
        entries[0]["description"] = "silently changed"
    elif attack == "original-line-changed":
        lines[0]["debit_minor"] = 67499
    elif attack == "extra-original-line":
        lines.append({**lines[0], "id": "new-hidden-original-line", "line_number": 3})
    elif attack == "unvalidated":
        entries[1]["status"] = "Draft"
    elif attack == "currency":
        entries[1]["currency_code"] = "EUR"
    elif attack == "precision-bool":
        entries[1]["currency_precision"] = True
    elif attack == "balanced-amount-tamper":
        lines[2]["debit_minor"] = lines[3]["credit_minor"] = 53000
        entries[1]["total_debit_minor"] = entries[1]["total_credit_minor"] = 53000
    elif attack == "extra-offsetting-lines":
        lines.extend(({**lines[2], "id": "extra-debit", "line_number": 3}, {**lines[3], "id": "extra-credit", "line_number": 4}))
    elif attack == "duplicate-line-id":
        lines[3]["id"] = lines[2]["id"]
    elif attack == "line-order":
        lines[3]["line_number"] = 3
    elif attack == "header-total":
        entries[2]["total_credit_minor"] = 15999
    elif attack == "boolean-money":
        lines[2]["credit_minor"] = False
    elif attack == "float-money":
        lines[2]["debit_minor"] = 54000.0
    elif attack == "unknown-account":
        lines[2]["account_id"] = "foreign-account"
    else:
        lines[2]["credit_minor"] = 1
    after = {"finance_posting_effects": tuple(effects), "finance_entries": tuple(entries), "finance_entry_lines": tuple(lines)}
    with pytest.raises(CycleRefusal):
        verify_posted_gl_amount_delta(original(), expected_cycle(original(), (Event("r", "Return", 0, quantity_scaled=12),))[0],
                                      before, after, accounts)


def raw_packet() -> dict[str, Any]:
    before, after, accounts = ledger_vector()
    shared = {"stock_sales_orders": ({"id": "stock", "invoice_id": "invoice", "quantity_precision": 0, "quantity_scaled": 15,
                                       "issue_plan": {"allocations": [{"cost_layer_id": "z-earlier-layer"}, {"cost_layer_id": "a-later-layer"}]}},),
              "ar_invoices": ({"id": "invoice", "total_minor": 67500, "currency_code": "USD", "currency_precision": 2},),
              "ar_receipt_allocations": ({"id": "allocation", "invoice_id": "invoice", "amount_minor": 10000},),
              "inventory_layer_consumptions": ({"id": "old-first", "cost_layer_id": "z-earlier-layer", "quantity_scaled": 10, "value_minor": 12000},
                                                {"id": "old-second", "cost_layer_id": "a-later-layer", "quantity_scaled": 5, "value_minor": 10000}),
              "finance_accounts": tuple({"id": value, "account_code": key} for key, value in accounts.items()),
              "customer_partial_return_history": (), "customer_partial_return_plans": (), "customer_partial_return_restorations": (),
              "inventory_movements": (), "inventory_movement_lines": ()}
    old = {**before, **deepcopy(shared), "inventory_cost_layers": (
        {"id": "z-earlier-layer", "remaining_quantity_scaled": 0, "remaining_value_minor": 0},
        {"id": "a-later-layer", "remaining_quantity_scaled": 5, "remaining_value_minor": 10000})}
    new = {**after, **deepcopy(shared), "inventory_cost_layers": (
        {"id": "z-earlier-layer", "remaining_quantity_scaled": 10, "remaining_value_minor": 12000},
        {"id": "a-later-layer", "remaining_quantity_scaled": 7, "remaining_value_minor": 14000}),
        "customer_partial_return_plans": ({"id": "return", "source_order_id": "stock", "invoice_id": "invoice", "phase": 2,
                                            "operation": "Return", "quantity_scaled": 12, "expected_history_version": 0},),
        "customer_partial_return_history": ({"sequence": 1, "kind": "Return", "plan_id": "return", "quantity_scaled": 12,
                                              "credit_minor": 54000, "cogs_minor": 16000, "amount_minor": 0},),
        "customer_partial_return_restorations": (
            {"plan_id": "return", "position": 1, "original_consumption_id": "old-first", "cost_layer_id": "z-earlier-layer",
             "offset_quantity_scaled": 0, "quantity_scaled": 10, "value_minor": 12000, "direction": 1},
            {"plan_id": "return", "position": 2, "original_consumption_id": "old-second", "cost_layer_id": "a-later-layer",
             "offset_quantity_scaled": 0, "quantity_scaled": 2, "value_minor": 4000, "direction": 1})}
    captures = [{name: [json.dumps({**row, "tenant_id": "tenant"}, sort_keys=True) for row in values] for name, values in capture.items()}
                for capture in (old, new)]
    for capture in captures:
        capture.update({name: [] for name in TABLES if name not in capture})
    return {"schema_version": "customer-partial-return-posted-cycle-input-v1", "tenant_id": "tenant", "source_order_id": "stock", "captures": captures}


def test_private_original_row_reader_derives_actual_effect_membership_and_fifo_amounts() -> None:
    proof = qualify_raw_cycle(raw_packet())
    assert (proof["events"], proof["new_actual_posting_effects"], proof["new_actual_posted_lines"]) == (1, 2, 4)
    assert proof["incremental_gl_fifo_layer_history_equal"] is True
    assert (proof["final_actual_posting_effects"], proof["final_actual_posted_lines"], proof["final_total_debit_minor"],
            proof["final_total_credit_minor"]) == (3, 6, 137500, 137500)


@pytest.mark.parametrize(("table", "field", "value"), [
    ("customer_partial_return_history", "credit_minor", 53999),
    ("customer_partial_return_history", "cogs_minor", 15999),
    ("customer_partial_return_history", "amount_minor", 1),
    ("customer_partial_return_history", "quantity_scaled", 13),
    ("customer_partial_return_plans", "expected_history_version", False),
    ("customer_partial_return_restorations", "value_minor", 11999),
    ("customer_partial_return_restorations", "direction", -1),
    ("inventory_cost_layers", "remaining_quantity_scaled", 11),
    ("finance_posting_effects", "tenant_id", "hidden-tenant"),
])
def test_private_original_row_reader_refuses_history_fifo_layer_and_scope_tampering(table: str, field: str, value: Any) -> None:
    packet = raw_packet()
    row = json.loads(packet["captures"][1][table][0])
    row[field] = value
    packet["captures"][1][table][0] = json.dumps(row, sort_keys=True)
    with pytest.raises(CycleRefusal):
        qualify_raw_cycle(packet)


@pytest.mark.parametrize("raw", ['{"id":"one","id":"two"}', '{"value":NaN}', '{"value":Infinity}', '[]',
                                  '{"value":1e999999999}', '{"value":999999999999999999999}'])
def test_original_json_parser_refuses_duplicate_keys_nonfinite_and_nonobjects(raw: str) -> None:
    with pytest.raises(CycleRefusal):
        decode_row(raw)


def test_original_json_parser_retains_exact_fraction_for_sql_numeric_tokens() -> None:
    assert decode_row('{"quantity":0.125,"minor":100}') == {"quantity": Fraction(1, 8), "minor": 100}


def test_populated_restore_requires_identical_original_membership_and_bytes() -> None:
    packet = raw_packet()
    restored = {"schema_version": "customer-partial-return-posted-restore-input-v1", "tenant_id": "tenant",
                "source_order_id": "stock", "capture": deepcopy(packet["captures"][-1])}
    require_proof = verify_raw_restore(packet, restored)
    assert require_proof["populated_restore_original_rows_equal"] is True and require_proof["restored_tables"] == len(TABLES) == 78
    for attack in ("missing-table", "extra-table", "missing-row", "changed-row"):
        candidate = deepcopy(restored)
        if attack == "missing-table":
            candidate["capture"].pop("finance_entries")
        elif attack == "extra-table":
            candidate["capture"]["unreviewed"] = []
        elif attack == "missing-row":
            candidate["capture"]["finance_entries"].pop()
        else:
            candidate["capture"]["finance_entries"][0] += " "
        with pytest.raises(CycleRefusal):
            verify_raw_restore(packet, candidate)


def audit_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def policy_event(sequence: int, previous: str, *, surface: str = "GET /api/v1/customer-partial-returns/plans",
                 actor: str = "poster", permission: str = "finance_core.read") -> dict[str, Any]:
    policy = {"schema_version": 1, "policy_version": "central-policy-v3", "allowed": True, "reason_code": "allowed",
              "evaluator": "central-policy", "principal_type": "user", "context_binding": "bound",
              "actor_digest": audit_hash({"namespace": "principal.actor", "value": actor}),
              "required_permission_digest": audit_hash({"namespace": "permission.contract", "values": [permission]}),
              "granted_permission_digest": audit_hash({"namespace": "permission.granted", "value": permission}),
              "context_digest": "a" * 64, "scope_digest": "b" * 64,
              "surface_digest": audit_hash({"namespace": "audit.surface", "value": surface}), "request_id_digest": "c" * 64}
    policy["decision_digest"] = audit_hash(policy)
    row = {"tenant_id": "tenant", "id": f"audit-{sequence}", "sequence": sequence, "previous_hash": previous,
           "actor_user_id": actor, "actor_label": "policy-engine", "object_type": "authorization.policy_decision",
           "object_id": policy["decision_digest"], "action": "evaluated", "before_hash": None,
           "after_hash": policy["decision_digest"], "metadata_json": {"policy_decision_evidence": policy, "request_id_digest": "c" * 64},
           "created_at": f"2026-10-15T00:00:{sequence:02d}+00:00"}
    return seal_audit(row)


def seal_audit(row: dict[str, Any]) -> dict[str, Any]:
    payload = {key: value for key, value in row.items() if key not in {"tenant_id", "event_hash"}}
    payload["metadata_json"] = json.dumps(row["metadata_json"], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    row["event_hash"] = audit_hash(payload)
    return row


def audit_capture(events: list[dict[str, Any]] | None = None) -> dict[str, list[str]]:
    """Only an observation-contract fixture; this is deliberately NOT a financial cycle."""
    result: dict[str, list[str]] = {name: [] for name in TABLES}
    result["customer_partial_return_plans"] = [json.dumps({"tenant_id": "tenant", "id": f"plan-{number}", "phase": 2,
        "source_order_id": "stock", "plan_digest": "d" * 64, "preparer_actor_id": "maker"}, sort_keys=True) for number in range(1, 9)]
    result["customer_partial_return_events"] = [json.dumps({"tenant_id": "tenant", "actor_id": "poster"})]
    set_audits(result, events or [])
    return result


def set_audits(capture: dict[str, list[str]], events: list[dict[str, Any]]) -> None:
    capture["domain_audit_events"] = sorted(json.dumps(row, sort_keys=True) for row in events)
    capture["domain_audit_ledger_state"] = [json.dumps({"tenant_id": "tenant", "last_sequence": len(events),
        "last_event_hash": events[-1]["event_hash"] if events else "0" * 64,
        "updated_at": events[-1]["created_at"] if events else "2026-10-15T00:00:00+00:00"}, sort_keys=True)]


def test_independent_audit_append_preserves_all_business_originals_and_verifies_canonical_head() -> None:
    before, after = audit_capture(), audit_capture([policy_event(1, "0" * 64)])
    proof = verify_audit_only_transition(before, after, tenant_id="tenant")
    assert proof == {"business_tables": 76, "business_original_rows_equal": True, "audit_original_prefix_equal": True,
                     "audit_chain_valid": True, "audit_actions_bound": True, "appended_audit_events": 1}
    assert verify_audit_only_transition(after, deepcopy(after), tenant_id="tenant")["appended_audit_events"] == 0


@pytest.mark.parametrize(("suffix", "permission", "rejected_permission"), [
    ("audit/verify", "audit.verify", "audit.read"),
    ("security/integrations", "security.policy.manage", "security.integrations.manage"),
    ("security/retention-policies", "security.policy.manage", "security.retention.manage"),
])
def test_admin_read_audit_contract_binds_the_exact_route_permission(
    suffix: str, permission: str, rejected_permission: str,
) -> None:
    # These finite permissions belong to the actual GET handlers; no mutation is admitted.
    surface = "GET /api/v1/admin/" + suffix
    before = audit_capture()
    after = audit_capture([policy_event(1, "0" * 64, surface=surface, permission=permission)])
    assert verify_audit_only_transition(before, after, tenant_id="tenant")["appended_audit_events"] == 1
    after = audit_capture([policy_event(1, "0" * 64, surface=surface, permission=rejected_permission)])
    with pytest.raises(CycleRefusal):
        verify_audit_only_transition(before, after, tenant_id="tenant")


@pytest.mark.parametrize("attack", ["business-add", "business-change", "old-byte-mutation", "old-resealed-mutation", "sequence-gap",
    "forged-head", "head-sequence", "head-time", "foreign-tenant", "duplicate", "unrelated-action", "unrelated-surface",
    "wrong-permission", "unbound-actor", "wrong-actor-digest", "policy-digest", "request-digest", "bad-previous", "missing-head", "unknown-table"])
def test_audit_observation_cannot_hide_business_changes_or_invalid_resealed_audit_history(attack: str) -> None:
    first = policy_event(1, "0" * 64)
    before, after = audit_capture([first]), audit_capture([first, policy_event(2, first["event_hash"])])
    events = [json.loads(raw) for raw in after["domain_audit_events"]]
    events.sort(key=lambda row: row["sequence"])
    current = events[-1]
    if attack == "business-add":
        after["finance_posting_effects"] = [json.dumps({"tenant_id": "tenant", "id": "extra-effect"})]
    elif attack == "business-change":
        after["customer_partial_return_plans"][0] += " "
    elif attack == "old-byte-mutation":
        after["domain_audit_events"][after["domain_audit_events"].index(json.dumps(first, sort_keys=True))] += " "
    elif attack == "old-resealed-mutation":
        events[0]["actor_label"] = "rewritten-original"
        seal_audit(events[0])
        current["previous_hash"] = events[0]["event_hash"]
    elif attack == "sequence-gap":
        current["sequence"] = 3
    elif attack == "foreign-tenant":
        current["tenant_id"] = "foreign"
    elif attack == "duplicate":
        after["domain_audit_events"].append(after["domain_audit_events"][0])
    elif attack == "unrelated-action":
        current["action"] = "posted"
    elif attack in {"unrelated-surface", "wrong-permission", "unbound-actor"}:
        current = policy_event(2, first["event_hash"], surface="POST /api/v1/admin/access/roles" if attack == "unrelated-surface"
                               else "GET /api/v1/customer-partial-returns/plans", permission="users.manage" if attack == "wrong-permission"
                               else "finance_core.read", actor="unbound-other-human" if attack == "unbound-actor" else "poster")
        events[-1] = current
    elif attack == "wrong-actor-digest":
        current["metadata_json"]["policy_decision_evidence"]["actor_digest"] = "e" * 64
    elif attack == "policy-digest":
        current["metadata_json"]["policy_decision_evidence"]["decision_digest"] = "e" * 64
    elif attack == "request-digest":
        current["metadata_json"]["request_id_digest"] = "e" * 64
    elif attack == "bad-previous":
        current["previous_hash"] = "e" * 64
    elif attack == "unknown-table":
        after["unreviewed"] = []
    if attack not in {"old-byte-mutation", "duplicate", "business-add", "business-change", "unknown-table"}:
        seal_audit(current)
        set_audits(after, events)
    if attack in {"forged-head", "head-sequence", "head-time"}:
        head = json.loads(after["domain_audit_ledger_state"][0])
        head[{"forged-head": "last_event_hash", "head-sequence": "last_sequence", "head-time": "updated_at"}[attack]] = 0 if attack == "head-sequence" else "e" * 64
        after["domain_audit_ledger_state"] = [json.dumps(head)]
    if attack == "missing-head":
        after["domain_audit_ledger_state"] = []
    with pytest.raises(CycleRefusal):
        verify_audit_only_transition(before, after, tenant_id="tenant")


def observations_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    """Metadata-only admission vectors; main financial reader must refuse them."""
    events = [policy_event(1, "0" * 64)]
    captures, observations = [], []
    for version in range(9):
        capture = audit_capture(deepcopy(events))
        capture["customer_partial_return_history"] = [json.dumps({"tenant_id": "tenant", "sequence": number, "plan_id": f"plan-{number}"}) for number in range(1, version + 1)]
        captures.append(capture)
        if version in {1, 6, 8}:
            events.append(policy_event(len(events) + 1, events[-1]["event_hash"]))
            observed = deepcopy(capture)
            set_audits(observed, deepcopy(events))
            observations.append({"schema_version": "customer-partial-return-browser-observation-v1", "kind": "FinalRead" if version == 8 else "RetainedReplay",
                "tenant_id": "tenant", "source_order_id": "stock", "history_version": version, "posted_plan_id": f"plan-{version}", "plan_digest": "d" * 64, "tables": observed})
    return ({"schema_version": "customer-partial-return-posted-cycle-input-v1", "tenant_id": "tenant", "source_order_id": "stock", "captures": captures},
            {"schema_version": "customer-partial-return-posted-observations-input-v1", "tenant_id": "tenant", "source_order_id": "stock", "observations": observations})


def test_three_closed_observations_bind_economic_versions_and_all_restored_final_originals() -> None:
    packet, observations = observations_contract()
    proof = verify_raw_observations(packet, observations)
    assert proof["observations"] == 3 and proof["observation_audit_appended_events"] == 3
    assert proof["observation_audit_chronology_valid"] is True
    restored = {"schema_version": "customer-partial-return-posted-restore-input-v1", "tenant_id": "tenant", "source_order_id": "stock",
                "capture": deepcopy(observations["observations"][-1]["tables"])}
    assert verify_raw_restore(packet, restored, observations=observations)["restore_uses_final_observation"] is True
    with pytest.raises(CycleRefusal):
        verify_raw_restore(packet, {**restored, "capture": packet["captures"][-1]}, observations=observations)
    with pytest.raises((CycleRefusal, KeyError)):
        qualify_raw_cycle(packet)  # Observation-only fixtures can never qualify financial posting.


@pytest.mark.parametrize("attack", ["wrong-version", "bool-version", "wrong-kind", "wrong-plan", "wrong-digest", "dropped-observation", "audit-rebranch", "business-delta", "replay-wrong-post", "final-post-action"])
def test_observation_affinity_and_chronology_cannot_be_reframed_as_business_replay(attack: str) -> None:
    packet, observations = observations_contract()
    current = observations["observations"][0]
    if attack == "wrong-version":
        current["history_version"] = 2
    if attack == "bool-version":
        current["history_version"] = True
    if attack == "wrong-kind":
        current["kind"] = "FinalRead"
    if attack == "wrong-plan":
        current["posted_plan_id"] = "plan-2"
    if attack == "wrong-digest":
        current["plan_digest"] = "e" * 64
    if attack == "dropped-observation":
        observations["observations"].pop()
    if attack == "audit-rebranch":
        set_audits(packet["captures"][2], [policy_event(1, "0" * 64)])
    if attack == "business-delta":
        current["tables"]["inventory_movements"] = [json.dumps({"tenant_id": "tenant", "id": "changed"})]
    if attack in {"replay-wrong-post", "final-post-action"}:
        current = observations["observations"][1 if attack == "replay-wrong-post" else 2]
        old = [json.loads(raw) for raw in packet["captures"][current["history_version"]]["domain_audit_events"]]
        old.sort(key=lambda row: row["sequence"])
        old.append(policy_event(len(old) + 1, old[-1]["event_hash"], surface="POST /api/v1/customer-partial-returns/plans/plan-1/post"))
        set_audits(current["tables"], old)
    with pytest.raises(CycleRefusal):
        verify_raw_observations(packet, observations)


def test_final_posted_totals_exclude_complete_unposted_and_void_entry_lines() -> None:
    _before, after, roles = ledger_vector()
    after["finance_accounts"] = tuple({"id": value, "account_code": key} for key, value in roles.items())
    for status in ("Draft", "Voided"):
        after["finance_entries"] += ({"id": status, "status": status, "currency_code": "USD", "currency_precision": 2,
                                     "total_debit_minor": 999, "total_credit_minor": 999},)
        after["finance_entry_lines"] += (
            {"id": status + "-1", "entry_id": status, "line_number": 1, "account_id": roles["AR"], "debit_minor": 999, "credit_minor": 0},
            {"id": status + "-2", "entry_id": status, "line_number": 2, "account_id": roles["REVENUE"], "debit_minor": 0, "credit_minor": 999})
    proof = posted_ledger_totals(original(), after)
    assert (proof["final_actual_posting_effects"], proof["final_actual_posted_lines"], proof["final_total_debit_minor"]) == (3, 6, 137500)
    assert proof["unposted_or_void_entries_excluded"] is True


@pytest.mark.parametrize("attack", ["duplicate-effect-entry", "unbalanced-original-line", "original-header-total", "unposted-effect", "unknown-account"])
def test_final_ledger_totals_refuse_invalid_posted_membership_and_balance(attack: str) -> None:
    _before, after, roles = ledger_vector()
    after["finance_accounts"] = tuple({"id": value, "account_code": key} for key, value in roles.items())
    if attack == "duplicate-effect-entry":
        after["finance_posting_effects"] += ({"id": "extra", "entry_id": "old-entry"},)
    elif attack == "unbalanced-original-line":
        after["finance_entry_lines"][0]["debit_minor"] = 67499
    elif attack == "original-header-total":
        after["finance_entries"][0]["total_credit_minor"] = 67499
    elif attack == "unposted-effect":
        after["finance_entries"][0]["status"] = "Draft"
    else:
        after["finance_entry_lines"][0]["account_id"] = "hidden-account"
    with pytest.raises(CycleRefusal):
        posted_ledger_totals(original(), after)
