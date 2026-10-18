"""Exact nonstatutory earnings, whole-entry claims and settlement invariants."""
from fractions import Fraction

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.people_project_payroll import TimeLine, TimeSubmission, earnings, half_even, integer, settlement


def approved(identifier: str, employee: str, rate: int, first: int, second: int) -> dict[str, object]:
    return {"id": identifier, "employee_id": employee, "employment_id": "EMP-" + employee,
            "status": "Approved", "approver_id": "independent-manager", "hourly_rate_minor": rate,
            "business_date": "2026-10-01", "lines": [
                {"project_id": "P1", "start_minute": 540, "end_minute": 540 + first},
                {"project_id": "P2", "start_minute": 540 + first, "end_minute": 540 + first + second}]}


def test_independent_fixture_and_two_partial_settlements() -> None:
    result = earnings([approved("T1", "E1", 1001, 61, 29), approved("T2", "E2", 999, 15, 45)])
    assert [item["gross_minor"] for item in result["employees"]] == [1502, 999]
    assert result["project_minor"] == {"P1": 1268, "P2": 1233} and result["gross_minor"] == 2501
    assert settlement(result, {}, {"E1": 1000})["amount_minor"] == 1000
    assert settlement(result, {"E1": 1000}, {"E1": 502, "E2": 999})["amount_minor"] == 1501
    with pytest.raises(FinancePostingError, match="exceeds"):
        settlement(result, {"E1": 1000}, {"E1": 503})


@pytest.mark.parametrize(("value", "expected"), [(Fraction(1, 2), 0), (Fraction(3, 2), 2), (Fraction(5, 2), 2), (Fraction(7, 2), 4)])
def test_half_even_ties_are_exact(value: Fraction, expected: int) -> None:
    assert half_even(value) == expected


@pytest.mark.parametrize("bad", [True, 1.0, "1", -1, 9_000_000_000_000_000_001])
def test_money_rejects_implicit_or_overflow_inputs(bad: object) -> None:
    with pytest.raises(FinancePostingError):
        integer(bad, "Money")


def test_permuted_full_sources_preserve_allocation_and_duplicate_source_refuses() -> None:
    one, two = approved("T1", "E1", 1001, 61, 29), approved("T2", "E2", 999, 15, 45)
    assert earnings([one, two]) == earnings([two, one])
    with pytest.raises(FinancePostingError, match="selected twice"):
        earnings([one, one])


def test_employee_day_intervals_refuse_overlap_or_noninteger_time() -> None:
    with pytest.raises(FinancePostingError, match="overlap"):
        TimeSubmission("E1", "2026-10-01", (TimeLine("P1", 540, 600), TimeLine("P2", 599, 610)), "Approved source")
    with pytest.raises(FinancePostingError):
        TimeLine("P1", False, 30)
