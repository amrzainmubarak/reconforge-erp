"""Literal vectors and bounded exhaustive properties for the independent v2 oracle."""
from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from typing import Any

import pytest

from tests.customer_partial_return_remainder_oracle import (
    POLICY,
    Birth,
    Consumption,
    History,
    RemainderRefusal,
    ReturnWitness,
    nearest,
    return_entries,
)


def birth(q: int, revenue: int, cost: int, *, paid: int = 0) -> Birth:
    return Birth(q, revenue, paid, (Consumption("original-consumption", q, cost),), "f" * 64, POLICY, "HALF_UP", "HALF_EVEN")


def cut(history: History, q: int, name: str = "cut") -> ReturnWitness:
    witness = history.propose_return(name, q, history.version)
    history.post_return(witness)
    return witness


@pytest.mark.parametrize(("pieces", "costs"), [((1, 1, 1), [334, 334, 333]), ((2, 1), [667, 334])])
def test_1001_over_three_uses_remaining_original_values_for_each_actual_partition(pieces: tuple[int, ...], costs: list[int]) -> None:
    history = History(birth(3, 1001, 1001))
    witnesses = [cut(history, q, f"cut-{index}") for index, q in enumerate(pieces)]
    assert [w.cost_minor for w in witnesses] == costs
    assert sum(w.cost_minor for w in witnesses) == 1001
    assert history.remaining == ((0, 0),)


def test_fractional_point_two_split_point_one_has_distinct_revenue_and_fifo_tie_policies() -> None:
    # All quantities are exact scaled integers: original0.2 and cuts0.1/0.1.
    history = History(birth(2, 5, 5))
    first, second = cut(history, 1, "first"), cut(history, 1, "second")
    assert [first.credit_minor, second.credit_minor] == [3, 2]
    assert [first.cost_minor, second.cost_minor] == [2, 3]
    assert [(p.before_quantity_scaled, p.before_value_minor) for p in (first.portions[0], second.portions[0])] == [(2, 5), (1, 3)]
    assert (second.revenue_before_quantity_scaled, second.revenue_before_value_minor) == (1, 2)


def test_reversal_restores_the_actual_previous_active_values_without_reallocating_the_original_cut() -> None:
    history = History(birth(3, 1001, 1001))
    cut(history, 1, "first")
    original = cut(history, 1, "second")
    assert original.cost_minor == 334 and history.remaining == ((1, 333),)
    inverse = history.reverse_latest("reverse-second", "second", history.version)
    assert inverse.witness is original and history.remaining == ((2, 667),)
    assert return_entries(original, reverse=True)[1] == ("ReverseCostRestoration", (("INVENTORY", 0, 334), ("COGS", 334, 0)))
    assert cut(history, 2, "remaining-two").cost_minor == 667
    assert history.restored_cost == 1001


def test_cross_layer_prefix_witnesses_use_original_consumption_order_and_reverse_the_exact_two_portions() -> None:
    source = Birth(5, 1009, 0, (Consumption("z-first", 3, 1001), Consumption("a-second", 2, 5)), "f" * 64, POLICY, "HALF_UP", "HALF_EVEN")
    history = History(source)
    first, second = cut(history, 1, "first"), cut(history, 1, "second")
    crossing = cut(history, 2, "crossing")
    assert [first.credit_minor, second.credit_minor, crossing.credit_minor] == [202, 202, 403]
    assert [first.cost_minor, second.cost_minor, crossing.cost_minor] == [334, 334, 335]
    assert [(p.consumption_id, p.quantity_scaled, p.value_minor, p.before_quantity_scaled, p.before_value_minor)
            for p in crossing.portions] == [("z-first", 1, 333, 1, 333), ("a-second", 1, 2, 2, 5)]
    history.reverse_latest("undo-crossing", "crossing", history.version)
    assert history.remaining == ((1, 333), (2, 5))
    assert cut(history, 2, "crossing-again").cost_minor == 335
    final = cut(history, 1, "final")
    assert (final.credit_minor, final.cost_minor) == (202, 3)


def test_all_zero_and_single_nonzero_return_leg_states_do_not_create_zero_journals() -> None:
    history = History(birth(3, 1, 1))
    witnesses = [cut(history, 1, f"cut-{index}") for index in range(3)]
    assert [(w.credit_minor, w.cost_minor) for w in witnesses] == [(0, 0), (1, 0), (0, 1)]
    assert [tuple(purpose for purpose, _lines in return_entries(w)) for w in witnesses] == [(), ("RevenueCredit",), ("CostRestoration",)]
    assert return_entries(witnesses[-1], reverse=True) == (("ReverseCostRestoration", (("INVENTORY", 0, 1), ("COGS", 1, 0))),)
    for witness in witnesses:
        for _purpose, lines in return_entries(witness):
            assert sum(left for _code, left, _right in lines) == sum(right for _code, _left, right in lines) > 0
            assert all((left > 0) != (right > 0) and left >= 0 and right >= 0 for _code, left, right in lines)


def test_zero_financial_legs_still_change_quantity_history_and_can_reverse_without_a_fake_effect() -> None:
    history = History(birth(3, 1, 1))
    original = cut(history, 1, "zero-financial-cut")
    assert return_entries(original) == () and (history.version, history.returned) == (1, 1)
    assert history.remaining == ((2, 1),)
    reversed_event = history.reverse_latest("reverse-zero", original.id, history.version)
    assert reversed_event.witness == original and return_entries(original, reverse=True) == ()
    assert (history.version, history.returned, history.credited, history.restored_cost) == (2, 0, 0, 0)
    assert history.remaining == ((3, 1),)


def test_mixed_zero_cost_portion_has_a_real_plan_cost_leg_owned_by_the_aggregate_cost() -> None:
    source = Birth(2, 1, 0, (Consumption("free-first", 1, 0), Consumption("valued-second", 1, 1)), "f" * 64, POLICY, "HALF_UP", "HALF_EVEN")
    witness = cut(History(source), 2)
    assert [p.value_minor for p in witness.portions] == [0, 1]
    assert witness.cost_minor == 1
    assert return_entries(witness)[1] == ("CostRestoration", (("INVENTORY", 1, 0), ("COGS", 0, 1)))
    # Native v3 binds every portion to that one real plan cost effect, including value0.


def test_latest_refund_reversal_then_return_reversal_restores_actual_prefix_and_no_older_operation_is_reversed() -> None:
    history = History(birth(2, 5, 5, paid=5))
    returned = cut(history, 1, "first")
    history.refund("cash", returned.id, 3, history.version)
    assert history.refund_due == 0
    with pytest.raises(RemainderRefusal):
        history.reverse_latest("wrong-order", returned.id, history.version)
    history.reverse_latest("reverse-cash", "cash", history.version)
    assert history.refund_due == 3
    history.reverse_latest("reverse-return", returned.id, history.version)
    assert (history.returned, history.credited, history.restored_cost, history.refunded) == (0, 0, 0, 0)
    assert history.remaining == ((2, 5),)


@pytest.mark.parametrize("attack", ["policy", "source", "future-version", "revenue-before", "portion-before-value", "portion-before-quantity", "offset", "consumption"])
def test_coherently_typed_but_forged_native_witness_fields_are_rejected_without_an_economic_transition(attack: str) -> None:
    history = History(birth(3, 1001, 1001))
    witness = history.propose_return("cut", 1, 0)
    if attack == "policy":
        witness = replace(witness, allocation_policy="legacy-exact-v1")
    elif attack == "source":
        witness = replace(witness, source_fingerprint="e" * 64)
    elif attack == "future-version":
        witness = replace(witness, history_version=1)
    elif attack == "revenue-before":
        witness = replace(witness, revenue_before_value_minor=1002)
    else:
        part = witness.portions[0]
        part = replace(part, **{"before_value_minor": 1002} if attack == "portion-before-value" else
                       {"before_quantity_scaled": 4} if attack == "portion-before-quantity" else
                       {"offset_quantity_scaled": 1} if attack == "offset" else {"consumption_id": "foreign-original"})
        witness = replace(witness, portions=(part,))
    before = vars(history).copy()
    with pytest.raises(RemainderRefusal):
        history.post_return(witness)
    assert vars(history) == before


def test_stale_prefix_and_duplicate_economic_history_are_not_new_effects() -> None:
    history = History(birth(3, 1001, 1001))
    stale = history.propose_return("stale", 1, 0)
    cut(history, 1, "other")
    before = vars(history).copy()
    with pytest.raises(RemainderRefusal):
        history.post_return(stale)
    with pytest.raises(RemainderRefusal):
        history.propose_return("other", 1, history.version)
    assert vars(history) == before


@pytest.mark.parametrize("bad", [True, False, -1, 0, 1.0, Fraction(1, 1), "1"])
def test_quantity_is_a_positive_scaled_integer_without_bool_or_float_coercion(bad: Any) -> None:
    history = History(birth(3, 5, 5))
    with pytest.raises(RemainderRefusal):
        history.propose_return("bad", bad, 0)


def test_source_birth_policy_cannot_be_silently_upgraded_or_replaced_by_current_policy() -> None:
    original = birth(3, 5, 5)
    for change in ({"allocation_policy": "legacy-exact-v1"}, {"revenue_rounding": "HALF_EVEN"}, {"fifo_rounding": "HALF_UP"}):
        with pytest.raises(RemainderRefusal):
            replace(original, **change)


def test_real_collection_prefix_changes_receivable_and_refund_entitlement_without_repricing_returned_revenue() -> None:
    source = Birth(15, 67500, 10000, (Consumption("first", 10, 12000), Consumption("second", 5, 10000)), "f" * 64, POLICY, "HALF_UP", "HALF_EVEN")
    history = History(source)
    first = cut(history, 12, "credit-first")
    assert (first.credit_minor, first.cost_minor, first.receivable_released_minor, first.refund_delta_minor) == (54000, 16000, 54000, 0)
    history.collect("cash-2000", 2000, history.version)
    assert (history.outstanding, history.collected) == (1500, 12000)
    before = vars(history).copy()
    with pytest.raises(RemainderRefusal):
        history.collect("overcap", 2000, history.version)
    assert vars(history) == before
    history.collect("cash-1500", 1500, history.version)
    final = cut(history, 3, "credit-final")
    assert (final.credit_minor, final.cost_minor, final.receivable_released_minor, final.refund_delta_minor) == (13500, 6000, 0, 13500)
    assert (history.outstanding, history.refund_due) == (0, 13500)


@pytest.mark.parametrize(("parent", "value"), [("return", 0), ("return", 4), ("foreign-return", 1)])
def test_refund_requires_a_positive_available_amount_and_an_active_same_source_return(parent: str, value: int) -> None:
    history = History(birth(2, 5, 5, paid=5))
    cut(history, 1, "return")
    before = vars(history).copy()
    with pytest.raises(RemainderRefusal):
        history.refund("invalid-refund", parent, value, history.version)
    assert vars(history) == before


def test_collection_cannot_be_reversed_as_a_partial_return_and_zero_cash_is_not_an_economic_event() -> None:
    history = History(birth(2, 5, 5))
    with pytest.raises(RemainderRefusal):
        history.collect("zero", 0, 0)
    history.collect("real-cash", 1, 0)
    before = vars(history).copy()
    with pytest.raises(RemainderRefusal):
        history.reverse_latest("wrong-owner-inverse", "real-cash", history.version)
    assert vars(history) == before


def test_zero_rounded_value_does_not_make_a_wrong_before_witness_valid() -> None:
    history = History(birth(3, 1, 1))
    witness = history.propose_return("zero", 1, 0)
    assert witness.cost_minor == 0 and nearest(Fraction(0, 3), "HALF_EVEN") == 0
    forged = replace(witness, portions=(replace(witness.portions[0], before_value_minor=0),))
    with pytest.raises(RemainderRefusal):
        history.post_return(forged)
    assert history.version == 0 and history.remaining == ((3, 1),)


def test_bool_minor_and_reordered_equal_value_consumptions_cannot_hide_a_forged_prefix() -> None:
    source = Birth(2, 2, 0, (Consumption("first", 1, 1), Consumption("second", 1, 1)), "f" * 64, POLICY, "HALF_UP", "HALF_EVEN")
    history = History(source)
    witness = history.propose_return("full", 2, 0)
    with pytest.raises(RemainderRefusal):
        replace(witness, credit_minor=True)
    with pytest.raises(RemainderRefusal):
        history.post_return(replace(witness, portions=tuple(reversed(witness.portions))))
    assert history.version == 0


def test_zero_leg_operations_still_consume_the_fixed_history_capacity_and_cannot_append_version_257() -> None:
    history = History(birth(300, 1, 1))
    for index in range(256):
        assert return_entries(cut(history, 1, f"zero-{index}")) == ()
    assert history.version == 256 and history.remaining == ((44, 1),)
    before = vars(history).copy()
    with pytest.raises(RemainderRefusal):
        history.propose_return("overflow", 1, 256)
    with pytest.raises(RemainderRefusal):
        history.reverse_latest("overflow-reverse", "zero-255", 256)
    assert vars(history) == before


def compositions(total: int) -> list[tuple[int, ...]]:
    if total == 0:
        return [()]
    return [(first, *rest) for first in range(1, total + 1) for rest in compositions(total - first)]


@pytest.mark.parametrize("quantity", range(1, 8))
def test_exhaustive_ordered_partitions_conserve_exact_original_money_and_reversal_restores_each_active_prefix(quantity: int) -> None:
    for revenue in range(1, 8):
        for cost in range(8):
            for partition in compositions(quantity):
                history = History(birth(quantity, revenue, cost, paid=revenue // 2))
                prefixes = []
                for index, q in enumerate(partition):
                    prefixes.append((history.remaining, history.returned, history.credited, history.restored_cost))
                    witness = cut(history, q, f"cut-{index}")
                    assert witness.credit_minor <= witness.revenue_before_value_minor
                    assert history.returned + sum(q for q, _value in history.remaining) == quantity
                    assert history.restored_cost + sum(value for _q, value in history.remaining) == cost
                    assert 0 <= history.credited <= revenue and history.refund_due >= 0
                assert (history.returned, history.credited, history.restored_cost) == (quantity, revenue, cost)
                for index in reversed(range(len(partition))):
                    history.reverse_latest(f"reverse-{index}", f"cut-{index}", history.version)
                    assert (history.remaining, history.returned, history.credited, history.restored_cost) == prefixes[index]


def test_nearest_tie_rules_are_invariant_to_fraction_representation_and_leave_integers_exact() -> None:
    assert [nearest(Fraction(5, 2), policy) for policy in ("HALF_UP", "HALF_EVEN")] == [3, 2]
    assert [nearest(Fraction(7, 2), policy) for policy in ("HALF_UP", "HALF_EVEN")] == [4, 4]
    assert nearest(Fraction(1001 * 2, 3), "HALF_EVEN") == 667
    assert nearest(Fraction(667, 2), "HALF_EVEN") == 334
    assert all(nearest(Fraction(i, 1), rule) == i for i in range(20) for rule in ("HALF_UP", "HALF_EVEN"))


@pytest.mark.parametrize(("selected", "expected"), [
    (4499999999999499999, 4499999999999),
    (8999999999999999999, 9000000000000),
])
def test_bigint_boundary_ratios_do_not_round_the_quotient_before_applying_the_captured_integer_policy(
    selected: int, expected: int,
) -> None:
    # Q uses precision6; a one-minor-unit quote gives the exact original G below.
    # The first exact ratio ends in .499999; finite intermediate scale must not
    # turn it into .5000. The second is just below an integer and must not add1.
    history = History(birth(9000000000000000000, 9000000000000, 9000000000000))
    first = cut(history, selected, "large-first")
    assert first.credit_minor == first.cost_minor == expected
    assert first.cost_minor <= first.portions[0].before_value_minor
    final = cut(history, history.birth.quantity_scaled - selected, "large-final")
    assert first.credit_minor + final.credit_minor == 9000000000000
    assert first.cost_minor + final.cost_minor == 9000000000000
    assert history.remaining == ((0, 0),)
