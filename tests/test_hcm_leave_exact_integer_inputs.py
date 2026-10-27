"""Leave day/count boundaries must protect direct domain callers as well as HTTP."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from reconforge.domain.hcm_leave import (
    HCMLeaveError,
    LeaveEntitlementBalance,
    LeaveRequest,
    accrue_monthly_entitlement,
    accrue_prorated_entitlement,
    approve_leave_request,
    calculate_unpaid_leave_deduction,
    cancel_leave_request,
    rollover_leave_entitlement,
)

INVALID_COUNTS = [True, False, 1.0, 1.5, Decimal("1"), "1", float("nan"), float("inf")]


def _request(days: Any, *, unpaid: bool = False) -> LeaveRequest:
    return LeaveRequest(
        request_id="REQ-EXACT", employee_id="EMP-EXACT", employee_user_id="alice",
        leave_type="Unpaid" if unpaid else "Annual", start_date="2026-12-01", end_date="2026-12-05",
        requested_days=days, status="Submitted", reason="Synthetic exact-day regression",
    )


def _balance() -> LeaveEntitlementBalance:
    return LeaveEntitlementBalance("EMP-EXACT", "Annual", 30, 20, 0)


@pytest.mark.parametrize("value", INVALID_COUNTS)
@pytest.mark.parametrize(("field", "code"), [
    ("annual_entitlement_days", "leave_entitlement_invalid"),
    ("accrued_days", "leave_balance_invalid"),
    ("consumed_days", "leave_balance_invalid"),
])
def test_balance_counts_reject_non_integer_values(field: str, code: str, value: Any) -> None:
    fields: dict[str, Any] = dict(employee_id="EMP-EXACT", leave_type="Annual", annual_entitlement_days=30, accrued_days=20, consumed_days=0)
    fields[field] = value
    with pytest.raises(HCMLeaveError) as caught:
        LeaveEntitlementBalance(**fields)
    assert caught.value.code == code


@pytest.mark.parametrize("value", INVALID_COUNTS)
def test_request_days_reject_non_integer_values_before_payroll(value: Any) -> None:
    with pytest.raises(HCMLeaveError) as caught:
        _request(value, unpaid=True)
    assert caught.value.code == "leave_days_invalid"


def test_fractional_unpaid_leave_never_produces_a_float_deduction() -> None:
    with pytest.raises(HCMLeaveError) as caught:
        result = calculate_unpaid_leave_deduction(_request(1.5, unpaid=True), 100)
        assert type(result) is int, f"Fractional leave escaped into payroll: {result!r} ({type(result).__name__})"
    assert caught.value.code == "leave_days_invalid"


@pytest.mark.parametrize("value", INVALID_COUNTS)
@pytest.mark.parametrize(("operation", "parameter", "code"), [
    ("monthly", "completed_months", "leave_service_invalid"),
    ("prorated", "service_days", "leave_service_days_invalid"),
    ("prorated", "total_year_days", "leave_year_days_invalid"),
    ("rollover", "max_carryover_days", "leave_carryover_invalid"),
])
def test_accrual_and_rollover_counts_reject_non_integer_values(
    operation: str, parameter: str, code: str, value: Any,
) -> None:
    with pytest.raises(HCMLeaveError) as caught:
        if operation == "monthly":
            accrue_monthly_entitlement(_balance(), completed_months=value)
        elif operation == "prorated":
            params: dict[str, Any] = {"service_days": 1, "total_year_days": 365}
            params[parameter] = value
            accrue_prorated_entitlement(_balance(), **params)
        else:
            rollover_leave_entitlement(_balance(), max_carryover_days=value)
    assert caught.value.code == code


def test_valid_integer_leave_operations_keep_exact_business_results() -> None:
    monthly = accrue_monthly_entitlement(_balance(), 1)
    assert monthly.accrued_days == 2 and type(monthly.accrued_days) is int
    prorated = accrue_prorated_entitlement(_balance(), 61, 366)
    assert prorated.accrued_days == 5 and type(prorated.accrued_days) is int
    approved, consumed = approve_leave_request(_request(3), _balance(), "manager")
    assert consumed.consumed_days == 3 and type(consumed.consumed_days) is int
    cancelled, restored = cancel_leave_request(approved, consumed, "2026-11-01")
    assert cancelled.status == "Cancelled" and restored.consumed_days == 0
    assert type(restored.available_days) is int
    rolled, forfeited = rollover_leave_entitlement(consumed, 5)
    assert rolled.accrued_days == 5 and forfeited == 12 and type(forfeited) is int
    deduction = calculate_unpaid_leave_deduction(_request(3, unpaid=True), 101)
    assert deduction == 303 and type(deduction) is int


@pytest.mark.parametrize(("annual", "accrued", "consumed", "code"), [
    (-1, 0, 0, "leave_entitlement_invalid"),
    (366, 0, 0, "leave_entitlement_invalid"),
    (30, -1, 0, "leave_balance_invalid"),
    (30, 10, -1, "leave_balance_invalid"),
    (30, 10, 11, "leave_overdrawn"),
])
def test_existing_integer_numeric_bounds_and_codes_are_preserved(annual: int, accrued: int, consumed: int, code: str) -> None:
    with pytest.raises(HCMLeaveError) as caught:
        LeaveEntitlementBalance("EMP-EXACT", "Annual", annual, accrued, consumed)
    assert caught.value.code == code
