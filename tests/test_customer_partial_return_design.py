"""Planned CR2 arithmetic vectors; no runtime accounting or native acceptance.

The proposed first scope refuses non-additive original minor-unit portions.
These stdlib derivations do not import the application's cost/credit engines.
"""
import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

DESIGN = json.loads((Path(__file__).parent / "fixtures/customer-partial-return-design-v1.json").read_text())


def exact(value: Any, *, zero: bool = False) -> int:
    if type(value) is not int or not (0 if zero else 1) <= value <= 9_000_000_000_000_000_000:
        raise ValueError("Design values require bounded exact original integers")
    return value


def derive(case: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive each original consumption portion and AR-first split independently."""
    quantity, gross = exact(case["quantity_scaled"]), exact(case["gross_minor"])
    collected = exact(case["collected_minor"], zero=True)
    scale, precision = exact(case["quantity_precision"], zero=True), exact(case["currency_precision"], zero=True)
    if scale > 6 or precision > 8 or Fraction(quantity * exact(case["net_unit_price_minor"]), 10**scale) != gross:
        raise ValueError("First design scope refuses non-additive original revenue portions")
    originals = case["consumptions"]
    if not 1 <= len(originals) <= 32 or len({row["id"] for row in originals}) != len(originals):
        raise ValueError("Complete original consumption identities must be bounded and unique")
    if sum(exact(row["quantity_scaled"]) for row in originals) != quantity or collected > gross:
        raise ValueError("Original source quantity and retained collections differ")
    returned, credited, restored, liability = 0, 0, 0, 0
    progress = {row["id"]: 0 for row in originals}
    results = []
    for step in case["steps"]:
        addition = exact(step["collect_before_minor"], zero=True)
        if addition > max(gross - credited - collected, 0):
            raise ValueError("New collection exceeds current credit-adjusted AR")
        collected += addition
        selected = exact(step["quantity_scaled"])
        if returned + selected > quantity:
            raise ValueError("Partial returns exceed the original delivered quantity")
        ratio = Fraction(gross * selected, quantity)
        if ratio.denominator != 1:
            raise ValueError("First design scope refuses non-additive original revenue portions")
        credit = ratio.numerator
        pending, cost, portions = selected, 0, []
        for original in originals:
            take = min(pending, original["quantity_scaled"] - progress[original["id"]])
            if not take:
                continue
            value = Fraction(exact(original["value_minor"]) * take, original["quantity_scaled"])
            if value.denominator != 1 or value <= 0:
                raise ValueError("First design scope refuses non-additive original cost portions")
            portions.append({"original_consumption_id": original["id"], "cost_layer_id": original["layer_id"],
                "quantity_scaled": take, "value_minor": value.numerator})
            progress[original["id"]] += take
            cost += value.numerator
            pending -= take
            if not pending:
                break
        outstanding_before = max(gross - credited - collected, 0)
        release = min(credit, outstanding_before)
        refund = credit - release
        returned, credited, restored, liability = returned + selected, credited + credit, restored + cost, liability + refund
        results.append({"credit_minor": credit, "cost_minor": cost, "ar_release_minor": release, "refund_delta_minor": refund,
            "outstanding_minor": max(gross - credited - collected, 0), "portions": portions,
            "returned_quantity_scaled": returned, "credited_minor": credited, "restored_cost_minor": restored,
            "collected_minor": collected, "refund_entitlement_minor": liability})
    refunded = sum(exact(value) for value in case["refunds_minor"])
    if refunded > liability:
        raise ValueError("Refund installments exceed the retained posted liability")
    return results


@pytest.mark.parametrize("case", DESIGN["cases"], ids=lambda case: case["id"])
def test_planned_partial_quantities_preserve_original_cost_credit_and_customer_net(case: dict[str, Any]) -> None:
    before = deepcopy(case)
    results = derive(case)
    for step, result in zip(case["steps"], results, strict=True):
        assert {key: result[key] for key in ("credit_minor", "cost_minor", "ar_release_minor", "refund_delta_minor", "outstanding_minor")} == {
            key.removeprefix("expected_"): value for key, value in step.items() if key.startswith("expected_")}
        assert result["credit_minor"] == result["ar_release_minor"] + result["refund_delta_minor"]
        assert sum(part["value_minor"] for part in result["portions"]) == result["cost_minor"]
        # The two balanced correction groups preserve independent original accounts.
        assert Fraction(result["credit_minor"] + result["cost_minor"]) == result["ar_release_minor"] + result["refund_delta_minor"] + result["cost_minor"]
    final = results[-1]
    assert final["returned_quantity_scaled"] == case["quantity_scaled"] and final["credited_minor"] == case["gross_minor"]
    assert final["restored_cost_minor"] == sum(original["value_minor"] for original in case["consumptions"])
    assert final["refund_entitlement_minor"] == final["collected_minor"] and final["outstanding_minor"] == 0
    assert final["refund_entitlement_minor"] - sum(case["refunds_minor"]) == 0
    assert case == before


def test_planned_two_layer_return_crosses_only_retained_original_consumption_boundary() -> None:
    case = next(case for case in DESIGN["cases"] if case["id"] == "usd-two-original-layers")
    assert derive(case)[1]["portions"] == [
        {"original_consumption_id": "C1", "cost_layer_id": "L1", "quantity_scaled": 1, "value_minor": 1200},
        {"original_consumption_id": "C2", "cost_layer_id": "L2", "quantity_scaled": 1, "value_minor": 1500}]


@pytest.mark.parametrize("mutation,error", [
    ("over-return", "delivered quantity"), ("duplicate-original", "identities"), ("over-collection", "credit-adjusted"),
    ("over-refund", "liability"), ("non-additive-cost", "cost portions"), ("non-additive-revenue", "revenue portions"),
    ("bool-quantity", "integers"), ("float-value", "integers")])
def test_planned_first_scope_refuses_independent_nonconserving_vectors(mutation: str, error: str) -> None:
    case = deepcopy(DESIGN["cases"][0])
    if mutation == "over-return":
        case["steps"][0]["quantity_scaled"] = 4
    elif mutation == "duplicate-original":
        case["consumptions"] *= 2
    elif mutation == "over-collection":
        case["steps"][1]["collect_before_minor"] = 5001
    elif mutation == "over-refund":
        case["refunds_minor"] = [1]
    elif mutation == "non-additive-cost":
        case["consumptions"][0]["value_minor"] = 100
    elif mutation == "non-additive-revenue":
        case["gross_minor"] = 7501
    elif mutation == "bool-quantity":
        case["steps"][0]["quantity_scaled"] = True
    else:
        case["consumptions"][0]["value_minor"] = 3600.0
    with pytest.raises(ValueError, match=error):
        derive(case)
