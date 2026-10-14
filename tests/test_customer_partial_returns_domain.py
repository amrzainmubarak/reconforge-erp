"""Pure CR2 foundations; synthetic inputs and an independent Fraction oracle.

No DB, API, authorization, posting or end-to-end capability is asserted here.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from reconforge.domain.customer_partial_returns import (
    MAX_CONSUMPTIONS,
    MAX_HISTORY_EVENTS,
    MAX_ORIGINAL_SNAPSHOT_BYTES,
    OriginalConsumption,
    OriginalPartialReturnSource,
    OriginalPostingEvidence,
    PartialReturnHistory,
    PartialReturnScope,
    apply_partial_return,
    collect_partial_return,
    partial_return_balance,
    prepare_partial_return,
    refund_partial_return,
    verify_partial_return_plan,
)
from reconforge.domain.finance_policy import FinanceCurrencyPolicy
from reconforge.domain.finance_posting import (
    FinancePostingError,
    canonical_json,
    digest_payload,
    make_entry_snapshot,
    validation_digest,
)
from reconforge.utils.money import CurrencyRegistryContext
from tests.test_customer_partial_return_design import DESIGN, derive


def source_for(case: dict[str, Any]) -> OriginalPartialReturnSource:
    """Hand-authored original source pins; captured bundled context stays local."""
    context = CurrencyRegistryContext.from_snapshot(json.loads(
        (Path(__file__).parents[1] / "reconforge/data/currency_registry.v1.json").read_text(encoding="utf-8"),
    ))
    policy = FinanceCurrencyPolicy.capture(case["currency_code"], context)
    assert policy.precision == case["currency_precision"]
    scope = PartialReturnScope("TENANT", "WORKSPACE", "ORGANIZATION", "ENTITY", "ITEM", "WAREHOUSE", "BASE-UOM")
    source_id, invoice_id = "STOCK-ORDER", "AR-INVOICE"
    revenue_reference = "OPS1-" + digest_payload([scope.workspace_id, "ARInvoice", invoice_id])[:32]

    def evidence(name: str, debit_account: str, credit_account: str, amount: int, reference: str) -> OriginalPostingEvidence:
        header = {
            "id": f"ENTRY-{name}", "workspace_id": scope.workspace_id,
            "organization_id": scope.organization_id, "legal_entity_id": scope.legal_entity_id,
            "journal_id": f"JOURNAL-{name}", "period_id": "ORIGINAL-PERIOD",
            "entry_number": f"NUMBER-{name}", "posting_date": "2026-10-01",
            "description": "Synthetic original evidence", "external_reference": reference,
            "source_type": "Manual", "currency_code": policy.currency_code, **policy.metadata(),
            "preparer_actor_id": "ORIGINAL-PREPARER", "reverses_posting_id": None,
        }
        snapshot = make_entry_snapshot(header, [
            {"line_number": 1, "account_id": debit_account, "description": "Original debit",
             "debit_minor": amount, "credit_minor": 0, "dimensions": {"COST-CENTER": "MAIN"}},
            {"line_number": 2, "account_id": credit_account, "description": "Original credit",
             "debit_minor": 0, "credit_minor": amount, "dimensions": {}},
        ])
        return OriginalPostingEvidence(f"EFFECT-{name}", scope, canonical_json(snapshot), validation_digest(snapshot))

    consumptions = tuple(OriginalConsumption(
        position, row["id"], "ORIGINAL-VALUATION-LINE", row["layer_id"], scope,
        case["quantity_precision"], row["quantity_scaled"], row["value_minor"], policy.currency_code,
    ) for position, row in enumerate(case["consumptions"], 1))
    return OriginalPartialReturnSource(
        scope, source_id, invoice_id, "ORIGINAL-VALUATION-DOCUMENT", revenue_reference, case["quantity_precision"],
        case["quantity_scaled"], case["gross_minor"], case["net_unit_price_minor"], case["collected_minor"],
        policy, context,
        evidence("COGS", "COGS", "INVENTORY", sum(row.value_minor for row in consumptions), source_id),
        evidence("REVENUE", "AR", "REVENUE", case["gross_minor"], revenue_reference),
        consumptions, policy.currency_code, scope.uom_id,
    )


@pytest.mark.parametrize("case", DESIGN["cases"], ids=lambda case: case["id"])
def test_all_seven_manual_vectors_agree_with_independent_original_fraction_oracle(case: dict[str, Any]) -> None:
    original = deepcopy(case)
    history = PartialReturnHistory(source_for(case))
    first_history = history
    independent = derive(case)
    for step, expected in zip(case["steps"], independent, strict=True):
        if step["collect_before_minor"]:
            history = collect_partial_return(history, step["collect_before_minor"])
        previous = history
        plan = prepare_partial_return(history, step["quantity_scaled"])
        verify_partial_return_plan(plan)
        assert (plan.credit_minor, plan.cogs_restored_minor, plan.receivable_released_minor,
                plan.refund_entitlement_delta_minor, plan.outstanding_after_minor) == (
            expected["credit_minor"], expected["cost_minor"], expected["ar_release_minor"],
            expected["refund_delta_minor"], expected["outstanding_minor"],
        )
        assert [{"original_consumption_id": portion.original_consumption_id, "cost_layer_id": portion.cost_layer_id,
                 "quantity_scaled": portion.quantity_scaled, "value_minor": portion.value_minor}
                for portion in plan.portions] == expected["portions"]
        assert plan.source is history.source
        history = apply_partial_return(history, plan)
        assert previous.events == plan.history.events and previous is not history
        balance = partial_return_balance(history)
        assert (balance.returned_quantity_scaled, balance.credited_minor, balance.cogs_restored_minor,
                balance.collected_minor, balance.refund_entitlement_minor) == (
            expected["returned_quantity_scaled"], expected["credited_minor"], expected["restored_cost_minor"],
            expected["collected_minor"], expected["refund_entitlement_minor"],
        )
        # Independent account conservation: credit = AR released + customer liability.
        assert balance.credited_minor == balance.receivable_released_minor + balance.refund_entitlement_minor
        assert balance.outstanding_minor - balance.refund_due_minor == (
            case["gross_minor"] - balance.credited_minor - balance.collected_minor + balance.refunded_minor
        )
    for installment in case["refunds_minor"]:
        history = refund_partial_return(history, installment)
    balance = partial_return_balance(history)
    assert balance.returned_quantity_scaled == case["quantity_scaled"]
    assert balance.credited_minor == case["gross_minor"]
    assert balance.cogs_restored_minor == sum(row["value_minor"] for row in case["consumptions"])
    assert balance.outstanding_minor == balance.refund_due_minor == 0
    assert first_history.events == () and case == original


def test_consumption_order_is_reviewed_position_not_lexical_ids_and_prefix_offsets_are_exact() -> None:
    case = deepcopy(DESIGN["cases"][3])
    case["consumptions"][0].update(id="Z-FIRST", layer_id="Z-LAYER")
    case["consumptions"][1].update(id="A-SECOND", layer_id="A-LAYER")
    history = PartialReturnHistory(source_for(case))
    first = prepare_partial_return(history, 1)
    assert first.portions[0].original_consumption_id == "Z-FIRST"
    second = prepare_partial_return(apply_partial_return(history, first), 2)
    assert [(p.position, p.original_consumption_id, p.offset_quantity_scaled, p.quantity_scaled, p.value_minor)
            for p in second.portions] == [(1, "Z-FIRST", 1, 1, 1200), (2, "A-SECOND", 0, 1, 1500)]


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.0, "1", None, 9_000_000_000_000_000_001])
def test_untrusted_quantity_and_settlement_values_cannot_enter_exact_domain(value: Any) -> None:
    history = PartialReturnHistory(source_for(DESIGN["cases"][2]))
    for operation in (prepare_partial_return, collect_partial_return, refund_partial_return):
        with pytest.raises(FinancePostingError):
            operation(history, value)


@pytest.mark.parametrize("mutation", ["cost-nonintegral", "cost-zero", "revenue-nonintegral"])
def test_nonintegral_and_zero_original_portions_refuse_without_rounding(mutation: str) -> None:
    case = deepcopy(DESIGN["cases"][0])
    if mutation == "cost-nonintegral":
        case["consumptions"][0]["value_minor"] = 100
    elif mutation == "cost-zero":
        case["consumptions"][0]["value_minor"] = 1
    else:
        case.update(quantity_precision=1, quantity_scaled=10, gross_minor=1, net_unit_price_minor=1)
        case["consumptions"][0]["quantity_scaled"] = 10
    history = PartialReturnHistory(source_for(case))
    with pytest.raises(FinancePostingError) as failure:
        prepare_partial_return(history, 1)
    assert failure.value.code == "partial_return_nonintegral"
    assert history.events == ()


def test_return_collection_and_refund_caps_use_the_same_credit_adjusted_invoice_state() -> None:
    history = PartialReturnHistory(source_for(DESIGN["cases"][1]))
    with pytest.raises(FinancePostingError, match="remaining original delivery"):
        prepare_partial_return(history, 4)
    with pytest.raises(FinancePostingError, match="retained entitlement"):
        refund_partial_return(history, 1)
    history = apply_partial_return(history, prepare_partial_return(history, 1))
    assert partial_return_balance(history).outstanding_minor == 0
    with pytest.raises(FinancePostingError, match="credit-adjusted invoice AR"):
        collect_partial_return(history, 1)
    history = apply_partial_return(history, prepare_partial_return(history, 1))
    history = refund_partial_return(history, 1250)
    assert partial_return_balance(history).refund_due_minor == 1250
    with pytest.raises(FinancePostingError, match="retained entitlement"):
        refund_partial_return(history, 1251)


def test_exact_plan_basis_refuses_replay_after_return_collection_or_refund_event() -> None:
    initial = PartialReturnHistory(source_for(DESIGN["cases"][1]))
    plan = prepare_partial_return(initial, 1)
    returned = apply_partial_return(initial, plan)
    collected = collect_partial_return(initial, 1)
    for newer in (returned, collected):
        with pytest.raises(FinancePostingError) as failure:
            apply_partial_return(newer, plan)
        assert failure.value.code == "partial_return_plan_stale"
    refunded_basis = apply_partial_return(returned, prepare_partial_return(returned, 1))
    next_plan = prepare_partial_return(refunded_basis, 1)
    with pytest.raises(FinancePostingError, match="stale plan"):
        apply_partial_return(refund_partial_return(refunded_basis, 1), next_plan)


@pytest.mark.parametrize("field,value", [
    ("credit_minor", 2501), ("cogs_restored_minor", 1201), ("receivable_released_minor", 1),
    ("refund_entitlement_delta_minor", 1), ("outstanding_after_minor", 1),
    ("quantity_before_scaled", 1), ("returned_quantity_scaled", 2),
    ("expected_version", 1), ("history_fingerprint", "a" * 64), ("source_fingerprint", "b" * 64),
])
def test_balanced_looking_caller_plan_changes_are_recomputed_and_refused(field: str, value: Any) -> None:
    history = PartialReturnHistory(source_for(DESIGN["cases"][1]))
    plan = replace(prepare_partial_return(history, 1), **{field: value})
    with pytest.raises(FinancePostingError) as failure:
        verify_partial_return_plan(plan)
    assert failure.value.code == "partial_return_plan_changed"


@pytest.mark.parametrize("mutation", ["reorder", "omit", "duplicate", "old-prefix", "source", "portion", "settlement"])
def test_retained_history_mutation_cannot_change_prefix_or_cumulative_facts(mutation: str) -> None:
    history = PartialReturnHistory(source_for(DESIGN["cases"][1]))
    history = collect_partial_return(history, 1)
    history = apply_partial_return(history, prepare_partial_return(history, 1))
    history = apply_partial_return(history, prepare_partial_return(history, 1))
    events = list(history.events)
    if mutation == "reorder":
        events[0], events[1] = events[1], events[0]
    elif mutation == "omit":
        events.pop(0)
    elif mutation == "duplicate":
        events.insert(1, events[0])
    elif mutation == "old-prefix":
        events[2] = replace(events[2], previous_history_fingerprint=events[1].previous_history_fingerprint)
    elif mutation == "source":
        events[1] = replace(events[1], source_fingerprint="a" * 64)
    elif mutation == "portion":
        values = events[1].return_values
        assert values is not None
        bad_portion = replace(values.portions[0], offset_quantity_scaled=1)
        events[1] = replace(events[1], return_values=replace(values, portions=(bad_portion,)))
    else:
        events[0] = replace(events[0], amount_minor=2)
    with pytest.raises(FinancePostingError):
        partial_return_balance(PartialReturnHistory(history.source, tuple(events)))


def test_nested_money_source_history_and_fresh_accessors_remain_immutable() -> None:
    source = source_for(DESIGN["cases"][1])
    history = PartialReturnHistory(source)
    plan = prepare_partial_return(history, 1)
    digest, payload = plan.fingerprint, plan.payload()
    snapshot = source.original_cogs.snapshot()
    snapshot["lines"][0]["dimensions"]["COST-CENTER"] = "MUTATED"
    snapshot["entry"]["currency_precision"] = 8
    payload["portions"][0]["value_minor"] = 1
    context = source.registry_context.snapshot()
    context["registry_version"] = "MUTATED"
    assert source.original_cogs.snapshot()["lines"][0]["dimensions"] == {"COST-CENTER": "MAIN"}
    assert plan.fingerprint == digest
    verify_partial_return_plan(plan)
    for target, field, value in (
        (source.currency_policy, "precision", 8), (source.registry_context, "_specs", ()),
        (source, "collected_minor", 0), (plan.portions[0], "value_minor", 0), (history, "events", ()),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(target, field, value)
    assert type(source.consumptions) is type(plan.portions) is type(history.events) is tuple
    with pytest.raises(FinancePostingError):
        replace(source, consumptions=list(source.consumptions))
    with pytest.raises(FinancePostingError):
        PartialReturnHistory(source, [])


@pytest.mark.parametrize("field,value", [
    ("tax_minor", 1), ("tax_minor", False), ("functional_currency", "JPY"), ("base_uom_id", "OTHER-UOM"),
    ("inventory_lot_id", "LOT"), ("serial_tracked", True), ("serial_tracked", 0),
    ("quantity_precision", True), ("quantity_precision", 7), ("collected_minor", 7501),
    ("net_unit_price_minor", 2501), ("source_order_id", " OTHER "),
])
def test_first_scope_refuses_unsupported_or_inconsistent_source(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        replace(source_for(DESIGN["cases"][0]), **{field: value})


@pytest.mark.parametrize("mutation", ["position", "duplicate-id", "duplicate-layer", "scope", "currency", "scale", "quantity", "cost-float"])
def test_original_consumptions_are_complete_unique_and_source_affine(mutation: str) -> None:
    source = source_for(DESIGN["cases"][3])
    rows = list(source.consumptions)
    changes_by_mutation: dict[str, dict[str, Any]] = {
        "position": {"position": 1}, "duplicate-id": {"consumption_id": rows[0].consumption_id},
        "duplicate-layer": {"cost_layer_id": rows[0].cost_layer_id},
        "scope": {"scope": replace(source.scope, tenant_id="OTHER")}, "currency": {"currency_code": "JPY"},
        "scale": {"quantity_precision": 1}, "quantity": {"quantity_scaled": 4}, "cost-float": {"value_minor": 4500.0},
    }
    with pytest.raises(FinancePostingError):
        rows[1] = replace(rows[1], **changes_by_mutation[mutation])
        replace(source, consumptions=tuple(rows))


@pytest.mark.parametrize("mutation", ["bad-digest", "noncanonical", "duplicate-json-key", "oversized", "float-money", "wrong-reference", "wrong-scope", "original-inverse", "wrong-amount"])
def test_original_posting_content_and_native_reference_pins_cannot_be_counterfeited(mutation: str) -> None:
    source = source_for(DESIGN["cases"][0])
    evidence = source.original_revenue
    snapshot = evidence.snapshot()
    with pytest.raises(ValueError):
        if mutation == "bad-digest":
            changed = replace(evidence, validation_digest="a" * 64)
        elif mutation == "noncanonical":
            changed = replace(evidence, snapshot_json=json.dumps(snapshot))
        elif mutation == "duplicate-json-key":
            changed = replace(evidence, snapshot_json='{"entry":{},' + evidence.snapshot_json[1:])
        elif mutation == "oversized":
            changed = replace(evidence, snapshot_json=" " * (MAX_ORIGINAL_SNAPSHOT_BYTES + 1))
        else:
            if mutation == "float-money":
                snapshot["lines"][0]["debit_minor"] = 7500.0
            elif mutation == "wrong-reference":
                snapshot["entry"]["external_reference"] = source.invoice_id  # actual reference is existing OPS1 plan
            elif mutation == "wrong-scope":
                snapshot["entry"]["legal_entity_id"] = "OTHER"
            elif mutation == "original-inverse":
                snapshot["entry"]["reverses_posting_id"] = "ORIGINAL-EFFECT"
            else:
                snapshot["lines"][0]["debit_minor"] = 7501
                snapshot["lines"][1]["credit_minor"] = 7501
            changed = replace(evidence, snapshot_json=canonical_json(snapshot), validation_digest=validation_digest(snapshot))
        replace(source, original_revenue=changed)


def test_policy_and_original_identity_pins_reject_cross_source_reuse() -> None:
    source = source_for(DESIGN["cases"][0])
    with pytest.raises(ValueError):
        replace(source, currency_policy=replace(source.currency_policy, precision=True))
    with pytest.raises(ValueError):
        replace(source, currency_policy=replace(source.currency_policy, registry_digest="a" * 64))
    with pytest.raises(ValueError):
        replace(source, original_revenue=replace(source.original_revenue, posting_effect_id=source.original_cogs.posting_effect_id))
    plan = prepare_partial_return(PartialReturnHistory(source), 1)
    with pytest.raises(FinancePostingError, match="stale plan"):
        apply_partial_return(PartialReturnHistory(replace(source, valuation_document_id="OTHER-DOCUMENT")), plan)


def test_consumption_and_history_resource_bounds_are_finite_without_skips() -> None:
    source = source_for(DESIGN["cases"][0])
    with pytest.raises(FinancePostingError):
        replace(source, consumptions=source.consumptions * (MAX_CONSUMPTIONS + 1))
    history = collect_partial_return(PartialReturnHistory(source), 1)
    with pytest.raises(FinancePostingError):
        PartialReturnHistory(source, history.events * (MAX_HISTORY_EVENTS + 1))
    for _ in range(MAX_HISTORY_EVENTS - 1):
        history = collect_partial_return(history, 1)
    assert partial_return_balance(history).version == MAX_HISTORY_EVENTS
    with pytest.raises(FinancePostingError) as full:
        prepare_partial_return(history, 1)
    assert full.value.code == "partial_return_history_full"
    with pytest.raises(FinancePostingError):
        collect_partial_return(history, 1)


def test_maximum_exact_original_units_do_not_use_decimal_context_or_float_intermediates() -> None:
    maximum = 9_000_000_000_000_000_000
    case: dict[str, Any] = {"currency_code": "USD", "currency_precision": 2, "quantity_precision": 0,
            "quantity_scaled": maximum, "gross_minor": maximum, "net_unit_price_minor": 1,
            "collected_minor": maximum,
            "consumptions": [{"id": "C1", "layer_id": "L1", "quantity_scaled": maximum, "value_minor": maximum}]}
    history = PartialReturnHistory(source_for(case))
    plan = prepare_partial_return(history, maximum - 1)
    assert plan.credit_minor == plan.cogs_restored_minor == plan.refund_entitlement_delta_minor == maximum - 1
    history = apply_partial_return(history, plan)
    remainder = prepare_partial_return(history, 1)
    assert remainder.credit_minor == remainder.cogs_restored_minor == 1
    final = partial_return_balance(apply_partial_return(history, remainder))
    assert final.credited_minor == final.refund_entitlement_minor == final.cogs_restored_minor == maximum


def test_per_invoice_nonnegative_ar_does_not_net_a_refund_liability_against_another_invoice() -> None:
    paid = PartialReturnHistory(source_for(DESIGN["cases"][2]))
    paid = apply_partial_return(paid, prepare_partial_return(paid, 3))
    unpaid_source = replace(source_for(DESIGN["cases"][0]), valuation_document_id="SECOND-ORIGINAL-DOCUMENT")
    unpaid = PartialReturnHistory(unpaid_source)
    assert partial_return_balance(paid).outstanding_minor == 0
    assert partial_return_balance(paid).refund_due_minor == 7500
    assert partial_return_balance(unpaid).outstanding_minor == 7500
    assert sum(partial_return_balance(history).outstanding_minor for history in (paid, unpaid)) == 7500


@settings(max_examples=40, deadline=None, derandomize=True)
@given(quantity=st.integers(2, 30), unit_price=st.integers(1, 5000), first_fraction=st.integers(1, 29),
       collection_fraction=st.integers(0, 10), initial_fraction=st.integers(0, 10))
def test_generated_interleaved_collection_and_partial_refund_preserve_customer_net_position(
    quantity: int, unit_price: int, first_fraction: int, collection_fraction: int, initial_fraction: int,
) -> None:
    gross = quantity * unit_price
    collected = gross * initial_fraction // 10
    selected = 1 + first_fraction % (quantity - 1)
    case: dict[str, Any] = {"currency_code": "USD", "currency_precision": 2, "quantity_precision": 0,
            "quantity_scaled": quantity, "gross_minor": gross, "net_unit_price_minor": unit_price,
            "collected_minor": collected,
            "consumptions": [{"id": "C1", "layer_id": "L1", "quantity_scaled": quantity, "value_minor": quantity * 7}]}
    history = PartialReturnHistory(source_for(case))
    first_credit = Fraction(gross * selected, quantity)
    first = prepare_partial_return(history, selected)
    assert first.credit_minor == first_credit
    history = apply_partial_return(history, first)
    available = max(gross - int(first_credit) - collected, 0)
    addition = available * collection_fraction // 10
    if addition:
        history = collect_partial_return(history, addition)
    collected += addition
    last = prepare_partial_return(history, quantity - selected)
    assert Fraction(last.credit_minor) == Fraction(gross) - first_credit
    history = apply_partial_return(history, last)
    balance = partial_return_balance(history)
    assert balance.refund_due_minor == collected and balance.outstanding_minor == 0
    if collected:
        partial = max(1, collected // 3)
        history = refund_partial_return(history, partial)
        assert partial_return_balance(history).refund_due_minor == collected - partial
        if collected != partial:
            history = refund_partial_return(history, collected - partial)
    assert partial_return_balance(history).refund_due_minor == 0


@settings(max_examples=60, deadline=None, derandomize=True)
@given(
    quantities=st.lists(st.integers(1, 8), min_size=1, max_size=5),
    unit_costs=st.lists(st.integers(1, 10000), min_size=5, max_size=5),
    unit_price=st.integers(1, 10000), collected_fraction=st.integers(0, 10),
)
def test_generated_prefix_costs_and_split_vs_whole_preserve_independent_financial_conservation(
    quantities: list[int], unit_costs: list[int], unit_price: int, collected_fraction: int,
) -> None:
    quantity = sum(quantities)
    gross = quantity * unit_price
    case: dict[str, Any] = {"currency_code": "USD", "currency_precision": 2, "quantity_precision": 0,
            "quantity_scaled": quantity, "gross_minor": gross, "net_unit_price_minor": unit_price,
            "collected_minor": gross * collected_fraction // 10,
            "consumptions": [{"id": f"C{99 - index}", "layer_id": f"L{99 - index}",
                              "quantity_scaled": count, "value_minor": count * unit_costs[index]}
                             for index, count in enumerate(quantities)]}
    initial = PartialReturnHistory(source_for(case))
    whole = apply_partial_return(initial, prepare_partial_return(initial, quantity))
    split = initial
    expected_cost = Fraction(0)
    for index, count in enumerate(quantities):
        for offset in range(count):
            plan = prepare_partial_return(split, 1)
            independent_cost = Fraction(case["consumptions"][index]["value_minor"], count)
            assert Fraction(plan.cogs_restored_minor) == independent_cost
            assert Fraction(plan.credit_minor) == Fraction(gross, quantity)
            assert len(plan.portions) == 1 and plan.portions[0].offset_quantity_scaled == offset
            expected_cost += independent_cost
            split = apply_partial_return(split, plan)
    left, right = partial_return_balance(split), partial_return_balance(whole)
    assert (left.returned_quantity_scaled, left.credited_minor, left.cogs_restored_minor,
            left.receivable_released_minor, left.refund_entitlement_minor, left.outstanding_minor) == (
        right.returned_quantity_scaled, right.credited_minor, right.cogs_restored_minor,
        right.receivable_released_minor, right.refund_entitlement_minor, right.outstanding_minor,
    )
    assert left.cogs_restored_minor == expected_cost
    assert left.credited_minor == gross and left.refund_entitlement_minor == case["collected_minor"]
    assert left.receivable_released_minor + left.refund_entitlement_minor == gross
    if left.refund_due_minor:
        split = refund_partial_return(split, left.refund_due_minor)
    assert partial_return_balance(split).refund_due_minor == 0
