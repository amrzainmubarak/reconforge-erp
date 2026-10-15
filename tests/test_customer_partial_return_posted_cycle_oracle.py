"""Independent arithmetic/adversarial vectors; native row binding is separate."""
from __future__ import annotations

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
    prefix_portions,
    qualify_raw_cycle,
    verify_posted_gl_amount_delta,
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
