"""Independent integer/Fraction expectations for held and inspected ME2 output."""
from fractions import Fraction

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.manufacturing_execution_v2 import (
    claimed_cost,
    cost_claims,
    held_allocation,
    inspection_allocation,
    operation_reports,
    routing_operations,
)


def oracle(value: Fraction) -> int:
    whole, residual = divmod(value.numerator, value.denominator)
    return whole + int(2 * residual > value.denominator or 2 * residual == value.denominator and whole % 2)


def test_material_labor_overhead_quality_hold_two_tranches_conserve_actual_wip() -> None:
    material, labor, overhead = 2900, oracle(Fraction(60 * 600, 60)), oracle(Fraction(30 * 600, 60))
    total = material + labor + overhead
    assert total == 3800
    first = held_allocation(output_quantity=10, total_cost=total, produced_quantity=0, produced_cost=0, quantity=4)
    assert first["held_cost_minor"] == oracle(Fraction(total * 4, 10)) == 1520
    inspected = inspection_allocation(held_quantity=4, held_cost=1520, accepted_quantity=3, rejected_quantity=1)
    assert (inspected["accepted_cost_minor"], inspected["rejected_cost_minor"]) == (1140, 380)
    assert total - inspected["released_cost_minor"] == 2280
    final = held_allocation(output_quantity=10, total_cost=total, produced_quantity=4, produced_cost=1520, quantity=6)
    accepted = inspection_allocation(held_quantity=6, held_cost=final["held_cost_minor"], accepted_quantity=6, rejected_quantity=0)
    assert inspected["accepted_cost_minor"] + accepted["accepted_cost_minor"] == 3420
    assert total == 3420 + 380


def test_cumulative_residual_carries_last_original_minor_unit() -> None:
    produced = allocated = released = 0
    amounts = []
    for count in (2, 3, 2):
        held = held_allocation(output_quantity=7, total_cost=101, produced_quantity=produced, produced_cost=allocated, quantity=count)
        inspected = inspection_allocation(held_quantity=count, held_cost=held["held_cost_minor"], accepted_quantity=count, rejected_quantity=0)
        expected = oracle(Fraction((101 - allocated) * count, 7 - produced))
        assert held["held_cost_minor"] == expected
        amounts.append(expected)
        produced += count
        allocated += expected
        released += inspected["released_cost_minor"]
    assert amounts == [29, 43, 29]
    assert released == allocated == 101


@pytest.mark.parametrize("minutes,rate,expected", [(1, 90, 2), (1, 150, 2), (3, 50, 2), (60, 600, 600)])
def test_exact_half_even_original_expense_claim(minutes: int, rate: int, expected: int) -> None:
    assert claimed_cost(minutes, rate) == oracle(Fraction(minutes * rate, 60)) == expected


@pytest.mark.parametrize("value", [True, 1.0, "60", 0, -1])
def test_claim_time_never_coerces_or_accepts_zero(value: object) -> None:
    with pytest.raises(FinancePostingError):
        claimed_cost(value, 600)


def test_routing_and_actual_execution_complete_ordered_populations() -> None:
    route = routing_operations([
        {"sequence": 1, "workcenter_id": "ME2W-cut", "name": "Cut", "minutes_per_batch": 60},
        {"sequence": 2, "workcenter_id": "ME2W-test", "name": "Test", "minutes_per_batch": 20},
    ])
    reports = [{"sequence": 1, "minutes": 22, "evidence_reference": "SYN-CUT-1"},
               {"sequence": 2, "minutes": 8, "evidence_reference": "SYN-TEST-1"}]
    assert operation_reports(reports, route) == reports
    for malformed in (reports[:1], list(reversed(reports)), [reports[0], reports[0]], [{**reports[0], "sequence": True}, reports[1]]):
        with pytest.raises(FinancePostingError):
            operation_reports(malformed, route)


def test_claims_bind_distinct_original_effect_line_and_real_operation() -> None:
    route = [{"sequence": 1}]
    claim = {"effect_id": "FPE-source", "line_id": "GL-line", "kind": "Labor", "operation_sequence": 1,
             "minutes": 60, "rate_minor_per_hour": 600}
    assert cost_claims([claim], route)[0]["amount_minor"] == 600
    for malformed in ([claim, claim], [{**claim, "operation_sequence": 2}], [{**claim, "kind": "Unbacked"}]):
        with pytest.raises(FinancePostingError):
            cost_claims(malformed, route)


@pytest.mark.parametrize("accepted,rejected", [(3, 0), (4, 1), (True, 3), (3.0, 1)])
def test_quality_requires_exact_complete_held_quantity(accepted: object, rejected: object) -> None:
    with pytest.raises(FinancePostingError):
        inspection_allocation(held_quantity=4, held_cost=1520, accepted_quantity=accepted, rejected_quantity=rejected)  # type: ignore[arg-type]
