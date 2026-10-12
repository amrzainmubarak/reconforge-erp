"""Source-versus-cash preservation and independent exact schedule allocation."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from itertools import permutations

import pytest

from reconforge.domain.accrual_deferral import (
    MAX_MINOR,
    ScheduleTranche,
    allocated_tranches,
    attach_original,
    reversal_equation,
    source_equation,
    tranche_equation,
)
from reconforge.domain.finance_posting import FinancePostingError, validation_digest
from tests.accrual_deferral_fixture import paid_original, planned_source, preparation


def independent_allocations(amount: int, rows: tuple[tuple[str, int], ...]) -> dict[str, int]:
    total = sum(weight for _, weight in rows)
    exact = {identifier: Fraction(amount * weight, total) for identifier, weight in rows}
    result = {identifier: value.numerator // value.denominator for identifier, value in exact.items()}
    residual = amount - sum(result.values())
    for identifier in sorted(exact, key=lambda key: (-(exact[key] - result[key]), key))[:residual]:
        result[identifier] += 1
    return result


def test_planned_three_tranche_cycle_conserves_paid_voucher_and_exact_inverse() -> None:
    source, _ = planned_source()
    equation = source["equation"]
    assert equation["cash_changed_minor"] == -10001
    assert [row["amount_minor"] for row in equation["tranches"]] == [3334, 3334, 3333]
    assert equation["policy"]["currency_rounding_policy"] == "ROUND_HALF_UP"
    balances = {"PREPAID": 0, "EXPENSE": 0, "CASH": 0}
    def apply(rows):
        for row in rows:
            balances[row["account_code"]] += row["debit_minor"] - row["credit_minor"]
    apply(equation["lines"])
    for index, tranche in enumerate(equation["tranches"]):
        current = tranche_equation(source, tranche["id"])
        assert current["cash_changed_minor"] == 0
        apply(current["lines"])
        if index == 1:
            original = {"id": "AD1-tranche", "kind": "release", "phase": 2, "plan_digest": "a" * 64,
                "posting_effect_id": "native-original", "equation": current}
            inverse = reversal_equation(original)
            assert inverse["original_posting_effect_id"] == "native-original"
            apply(inverse["lines"])
            apply(current["lines"])
    assert balances == {"PREPAID": 0, "EXPENSE": 10001, "CASH": -10001}


@pytest.mark.parametrize("amount,weights", [
    (10001, (("C", 1), ("A", 1), ("B", 1))),
    (7, (("C", 2), ("A", 3), ("B", 4))),
    (MAX_MINOR, (("C", MAX_MINOR), ("A", MAX_MINOR - 1), ("B", 1))),
])
def test_existing_allocator_matches_independent_fraction_under_every_row_permutation(amount, weights) -> None:
    expected = independent_allocations(amount, weights)
    if 0 in expected.values():
        # A schedule refuses zero-value journal tranches instead of pretending
        # they were posted. The canonical allocator itself permits zeros.
        for order in permutations(weights):
            with pytest.raises(FinancePostingError, match="positive allocation"):
                allocated_tranches(amount, [{"id": key, "weight": value} for key, value in order])
    else:
        for order in permutations(weights):
            actual = allocated_tranches(amount, [{"id": key, "weight": value} for key, value in order])
            assert {row["id"]: row["amount_minor"] for row in actual} == expected


@pytest.mark.parametrize("mode", ["attach_paid_expense", "attach_prepaid_voucher"])
def test_original_paid_attachment_never_charges_cash_again_and_keeps_original_dimensions(mode) -> None:
    source, context = planned_source()
    request = preparation(mode).payload()
    effect, review, roles = paid_original(request)
    before = deepcopy(effect)
    attached = attach_original(request, effect, review, roles, context)
    equation = source_equation(request, context, attached)
    assert equation["cash_changed_minor"] == 0 and effect == before
    assert not any(row["account_code"] == "CASH" for row in equation["lines"])
    assert equation["native_effect_required"] is (mode == "attach_paid_expense")
    assert equation["external_original_membership"]["original_effect_id"] == "original-effect"
    source.update(request=request, equation=equation)
    release = tranche_equation(source, "T1")
    assert all(row["dimensions"] == {"project-id": "original-project"} for row in release["lines"])
    if mode == "attach_paid_expense":
        assert equation["lines"] == [
            {"account_code": "PREPAID", "debit_minor": 10001, "credit_minor": 0, "dimensions": {"project-id": "original-project"}},
            {"account_code": "EXPENSE", "debit_minor": 0, "credit_minor": 10001, "dimensions": {"project-id": "original-project"}},
        ]
    else:
        assert equation["lines"] == []


@pytest.mark.parametrize("mutation", ["amount", "scope", "currency", "policy", "source", "reversal", "actors", "review", "dimension", "complex"])
def test_attachment_refuses_changed_or_ineligible_original_paid_voucher(mutation) -> None:
    _, context = planned_source()
    request = preparation("attach_paid_expense").payload()
    effect, review, roles = paid_original(request)
    if mutation == "amount":
        request["amount_minor"] += 1
    elif mutation == "scope":
        request["legal_entity_id"] = "foreign"
    elif mutation == "currency":
        request["currency_code"] = "EUR"
    elif mutation == "policy":
        effect["snapshot"]["entry"]["currency_registry_version"] = "foreign"
    elif mutation == "source":
        effect["source_kind"] = "InventoryReceipt"
    elif mutation == "reversal":
        effect["reverses_effect_id"] = "another-effect"
    elif mutation == "actors":
        effect["posted_actor_id"] = review["validator_actor_id"]
    elif mutation == "review":
        review["validation_digest"] = "a" * 64
    elif mutation == "dimension":
        effect["snapshot"]["lines"][0]["dimensions"] = {"project-id": "changed"}
    elif mutation == "complex":
        effect["snapshot"]["lines"][0]["debit_minor"] = 5000
        effect["snapshot"]["lines"].insert(1, {**effect["snapshot"]["lines"][0], "line_number": 3, "debit_minor": 5001})
        effect["snapshot"]["lines"].sort(key=lambda row: row["line_number"])
        effect["validation_digest"] = validation_digest(effect["snapshot"])
        review["validation_digest"] = effect["validation_digest"]
    with pytest.raises(FinancePostingError):
        attach_original(request, effect, review, roles, context)


def test_functional_expense_accrual_has_no_new_cash_voucher_and_retains_next_period_exact_inverse() -> None:
    source, context = planned_source()
    request = preparation("expense_accrual").payload()
    source.update(request=request, equation=source_equation(request, context))
    assert source["equation"]["lines"] == [] and source["equation"]["native_effect_required"] is False
    for row in request["tranches"]:
        current = tranche_equation(source, row["id"])
        assert current["operation"] == "accrue" and current["lines"][1]["account_code"] == "ACCRUAL"
        assert current["cash_changed_minor"] == 0 and row["reversal_period_id"] != row["period_id"]


@pytest.mark.parametrize("amount", [0, -1, True, 1.0, "10001", MAX_MINOR + 1])
def test_source_money_requires_exact_positive_bounded_minor(amount) -> None:
    with pytest.raises(FinancePostingError):
        replace(preparation(), amount_minor=amount).payload()


@pytest.mark.parametrize("change", ["duplicate_id", "duplicate_period", "before_source", "float_weight", "too_many", "zero_allocation", "unwanted_original", "missing_original", "reverse_same_period", "reverse_before"])
def test_schedule_rejects_ambiguous_source_periods_and_implicit_attachment(change) -> None:
    request = preparation()
    tranches = request.tranches
    if change == "duplicate_id":
        request = replace(request, tranches=(tranches[0], replace(tranches[1], id=tranches[0].id)))
    elif change == "duplicate_period":
        request = replace(request, tranches=(tranches[0], replace(tranches[1], period_id=tranches[0].period_id)))
    elif change == "before_source":
        request = replace(request, tranches=(replace(tranches[0], posting_date="2026-09-29"),))
    elif change == "float_weight":
        request = replace(request, tranches=(replace(tranches[0], weight=1.0),))
    elif change == "too_many":
        request = replace(request, tranches=tuple(ScheduleTranche(str(index), str(index), "2026-11-01", 1) for index in range(37)))
    elif change == "zero_allocation":
        request = replace(request, amount_minor=1)
    elif change == "unwanted_original":
        request = replace(request, original_effect_id="existing-paid")
    elif change == "missing_original":
        request = replace(preparation("attach_paid_expense"), original_effect_id=None)
    elif change == "reverse_same_period":
        request = replace(preparation("expense_accrual"), tranches=(ScheduleTranche("T", "P", "2026-11-01", 1, "P", "2026-12-01"),))
    elif change == "reverse_before":
        request = replace(preparation("expense_accrual"), tranches=(ScheduleTranche("T", "P", "2026-11-01", 1, "N", "2026-10-31"),))
    with pytest.raises(FinancePostingError):
        request.payload()


def test_tranche_and_inverse_require_actual_posted_original_membership() -> None:
    source, _ = planned_source()
    with pytest.raises(FinancePostingError):
        tranche_equation({**source, "phase": 1}, "T1")
    with pytest.raises(FinancePostingError):
        tranche_equation(source, "foreign")
    with pytest.raises(FinancePostingError):
        reversal_equation({"phase": 1, "kind": "release"})
