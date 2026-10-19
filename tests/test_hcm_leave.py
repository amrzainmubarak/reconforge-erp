"""Tests for HCM Leave entitlement, balance deduction, SoD enforcement, and cancellation."""

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
    reject_leave_request,
    rollover_leave_entitlement,
    submit_leave_request,
    withdraw_leave_request,
)


@pytest.fixture
def annual_balance() -> LeaveEntitlementBalance:
    return LeaveEntitlementBalance(
        employee_id="EMP-100",
        leave_type="Annual",
        annual_entitlement_days=24,  # 2 days per month
        accrued_days=12,             # 6 months accrued
        consumed_days=2,
    )


def test_leave_accrual_calculation(annual_balance: LeaveEntitlementBalance) -> None:
    # 6 months of service at 24 days/yr -> 12 days accrued
    updated = accrue_monthly_entitlement(annual_balance, completed_months=6)
    assert updated.accrued_days == 12
    assert updated.available_days == 10  # 12 accrued - 2 consumed

    # 12 months -> 24 days accrued
    full_year = accrue_monthly_entitlement(annual_balance, completed_months=12)
    assert full_year.accrued_days == 24
    assert full_year.available_days == 22


def test_leave_submission_and_balance_check(annual_balance: LeaveEntitlementBalance) -> None:
    req = LeaveRequest(
        request_id="REQ-001",
        employee_id="EMP-100",
        employee_user_id="USR-EMP-100",
        leave_type="Annual",
        start_date="2026-11-10",
        end_date="2026-11-14",
        requested_days=5,
        status="Draft",
        reason="Family vacation",
    )
    submitted = submit_leave_request(req, annual_balance)
    assert submitted.status == "Submitted"

    # Excess days beyond available (available is 10, request 15)
    req_excess = LeaveRequest(
        request_id="REQ-002",
        employee_id="EMP-100",
        employee_user_id="USR-EMP-100",
        leave_type="Annual",
        start_date="2026-11-10",
        end_date="2026-11-25",
        requested_days=15,
        status="Draft",
        reason="Extended travel",
    )
    with pytest.raises(HCMLeaveError, match="Insufficient leave balance"):
        submit_leave_request(req_excess, annual_balance)


def test_segregation_of_duties_self_approval_prohibited(annual_balance: LeaveEntitlementBalance) -> None:
    req = LeaveRequest(
        request_id="REQ-001",
        employee_id="EMP-100",
        employee_user_id="USR-EMP-100",
        leave_type="Annual",
        start_date="2026-11-10",
        end_date="2026-11-14",
        requested_days=5,
        status="Submitted",
        reason="Family vacation",
    )
    # Employee attempting to approve their own request must be blocked
    with pytest.raises(HCMLeaveError, match="Segregation of Duties violation"):
        approve_leave_request(req, annual_balance, approver_user_id="USR-EMP-100")


def test_valid_approval_and_cancellation_restoration(annual_balance: LeaveEntitlementBalance) -> None:
    req = LeaveRequest(
        request_id="REQ-001",
        employee_id="EMP-100",
        employee_user_id="USR-EMP-100",
        leave_type="Annual",
        start_date="2026-11-10",
        end_date="2026-11-14",
        requested_days=5,
        status="Submitted",
        reason="Family vacation",
    )
    # Manager approves
    approved_req, post_approve_bal = approve_leave_request(
        req, annual_balance, approver_user_id="USR-MGR-001"
    )
    assert approved_req.status == "Approved"
    assert approved_req.approved_by_user_id == "USR-MGR-001"
    assert post_approve_bal.consumed_days == 7  # 2 + 5
    assert post_approve_bal.available_days == 5  # 12 - 7

    # Cancel before start date (on 2026-11-01 < 2026-11-10)
    cancelled_req, post_cancel_bal = cancel_leave_request(
        approved_req, post_approve_bal, current_date="2026-11-01"
    )
    assert cancelled_req.status == "Cancelled"
    assert post_cancel_bal.consumed_days == 2  # Restored to 2
    assert post_cancel_bal.available_days == 10  # Restored to 10

    # Attempt to cancel after start date must be refused
    with pytest.raises(HCMLeaveError, match="Cannot cancel leave on or after start date"):
        cancel_leave_request(approved_req, post_approve_bal, current_date="2026-11-10")


def test_leave_rejection_flow(annual_balance: LeaveEntitlementBalance) -> None:
    req = LeaveRequest(
        request_id="REQ-003",
        employee_id="EMP-100",
        employee_user_id="USR-EMP-100",
        leave_type="Annual",
        start_date="2026-12-01",
        end_date="2026-12-05",
        requested_days=5,
        status="Submitted",
        reason="Winter holiday",
    )

    # 1. Self-rejection prohibited (SoD)
    with pytest.raises(HCMLeaveError, match="employees cannot review or reject their own"):
        reject_leave_request(req, annual_balance, rejector_user_id="USR-EMP-100", reason="Self rejection")

    # 2. Cannot reject non-submitted request (e.g. Draft)
    draft_req = LeaveRequest(
        request_id="REQ-004",
        employee_id="EMP-100",
        employee_user_id="USR-EMP-100",
        leave_type="Annual",
        start_date="2026-12-01",
        end_date="2026-12-05",
        requested_days=5,
        status="Draft",
        reason="Winter holiday",
    )
    with pytest.raises(HCMLeaveError, match="Only submitted requests can be rejected"):
        reject_leave_request(draft_req, annual_balance, rejector_user_id="USR-MGR-001", reason="Project critical")

    # 3. Employee mismatch between request and balance
    mismatched_bal = LeaveEntitlementBalance(
        employee_id="EMP-999",
        leave_type="Annual",
        annual_entitlement_days=24,
        accrued_days=12,
        consumed_days=0,
    )
    with pytest.raises(HCMLeaveError, match="Leave balance employee"):
        reject_leave_request(req, mismatched_bal, rejector_user_id="USR-MGR-001", reason="Project critical")

    # 4. Valid rejection by manager
    rejected = reject_leave_request(
        req,
        annual_balance,
        rejector_user_id="USR-MGR-001",
        reason="Critical project delivery milestone in December",
    )
    assert rejected.status == "Rejected"
    assert rejected.rejection_reason == "Critical project delivery milestone in December"
    # Invariant: balance is preserved intact
    assert annual_balance.consumed_days == 2
    assert annual_balance.available_days == 10


def test_leave_withdrawal_flow() -> None:
    # 1. Withdraw draft request
    draft_req = LeaveRequest(
        request_id="REQ-010",
        employee_id="EMP-100",
        employee_user_id="USR-EMP-100",
        leave_type="Annual",
        start_date="2026-12-10",
        end_date="2026-12-12",
        requested_days=3,
        status="Draft",
        reason="Personal errand",
    )
    withdrawn_draft = withdraw_leave_request(draft_req)
    assert withdrawn_draft.status == "Cancelled"

    # 2. Withdraw submitted request
    sub_req = LeaveRequest(
        request_id="REQ-011",
        employee_id="EMP-100",
        employee_user_id="USR-EMP-100",
        leave_type="Annual",
        start_date="2026-12-10",
        end_date="2026-12-12",
        requested_days=3,
        status="Submitted",
        reason="Personal errand",
    )
    withdrawn_sub = withdraw_leave_request(sub_req)
    assert withdrawn_sub.status == "Cancelled"

    # 3. Cannot withdraw approved request via withdraw_leave_request (must use cancel_leave_request)
    app_req = LeaveRequest(
        request_id="REQ-012",
        employee_id="EMP-100",
        employee_user_id="USR-EMP-100",
        leave_type="Annual",
        start_date="2026-12-10",
        end_date="2026-12-12",
        requested_days=3,
        status="Approved",
        reason="Personal errand",
        approved_by_user_id="USR-MGR-001",
    )
    with pytest.raises(HCMLeaveError, match="Only draft or submitted requests can be withdrawn"):
        withdraw_leave_request(app_req)


def test_leave_rollover_carryover_and_forfeiture() -> None:
    # Employee has 15 available days (20 accrued - 5 consumed)
    bal = LeaveEntitlementBalance(
        employee_id="EMP-100",
        leave_type="Annual",
        annual_entitlement_days=24,
        accrued_days=20,
        consumed_days=5,
    )

    # 1. Max carryover 10 days -> 10 carry over, 5 forfeited
    new_bal, forfeited = rollover_leave_entitlement(bal, max_carryover_days=10)
    assert forfeited == 5
    assert new_bal.accrued_days == 10
    assert new_bal.consumed_days == 0
    assert new_bal.available_days == 10
    assert new_bal.annual_entitlement_days == 24

    # 2. Max carryover 20 days -> 15 carry over, 0 forfeited
    new_bal_generous, forfeited_generous = rollover_leave_entitlement(bal, max_carryover_days=20)
    assert forfeited_generous == 0
    assert new_bal_generous.accrued_days == 15
    assert new_bal_generous.consumed_days == 0
    assert new_bal_generous.available_days == 15

    # 3. Zero carryover policy (use-it-or-lose-it)
    new_bal_zero, forfeited_all = rollover_leave_entitlement(bal, max_carryover_days=0)
    assert forfeited_all == 15
    assert new_bal_zero.accrued_days == 0
    assert new_bal_zero.consumed_days == 0
    assert new_bal_zero.available_days == 0

    # 4. Negative carryover validation
    with pytest.raises(HCMLeaveError, match="Max carryover days must be between 0 and 365"):
        rollover_leave_entitlement(bal, max_carryover_days=-1)


def test_leave_day_proration_accrual() -> None:
    bal = LeaveEntitlementBalance(
        employee_id="EMP-JOINER",
        leave_type="Annual",
        annual_entitlement_days=24,
        accrued_days=0,
        consumed_days=0,
    )

    # Mid-year joiner (182.5 days of 365) -> (24 * 182 + 182) // 365 = 4550 // 365 = 12 days
    prorated_182 = accrue_prorated_entitlement(bal, service_days=182, total_year_days=365)
    assert prorated_182.accrued_days == 12

    # Leap year (366 days)
    prorated_leap = accrue_prorated_entitlement(bal, service_days=183, total_year_days=366)
    assert prorated_leap.accrued_days == 12

    # Full year (365 days of 365) -> 24 days
    prorated_full = accrue_prorated_entitlement(bal, service_days=365, total_year_days=365)
    assert prorated_full.accrued_days == 24

    # Day 0 -> 0 days
    prorated_zero = accrue_prorated_entitlement(bal, service_days=0, total_year_days=365)
    assert prorated_zero.accrued_days == 0

    # Bounds validation
    with pytest.raises(HCMLeaveError, match="Service days must be between 0 and total year days"):
        accrue_prorated_entitlement(bal, service_days=400, total_year_days=365)
    with pytest.raises(HCMLeaveError, match="Service days must be between 0 and total year days"):
        accrue_prorated_entitlement(bal, service_days=-5, total_year_days=365)


def test_unpaid_leave_payroll_deduction() -> None:
    unpaid_req = LeaveRequest(
        request_id="REQ-UNPAID-01",
        employee_id="EMP-100",
        employee_user_id="USR-EMP-100",
        leave_type="Unpaid",
        start_date="2026-11-01",
        end_date="2026-11-04",
        requested_days=4,
        status="Approved",
        reason="Extended personal leave",
        approved_by_user_id="USR-MGR-001",
    )
    # Daily rate: 500.00 SAR (50,000 minor) -> 4 days * 50,000 = 200,000 minor (2,000.00 SAR)
    deduction = calculate_unpaid_leave_deduction(unpaid_req, daily_rate_minor=50_000)
    assert deduction == 200_000

    # Paid leave must have 0 unpaid deduction
    annual_req = LeaveRequest(
        request_id="REQ-ANNUAL-01",
        employee_id="EMP-100",
        employee_user_id="USR-EMP-100",
        leave_type="Annual",
        start_date="2026-11-01",
        end_date="2026-11-04",
        requested_days=4,
        status="Approved",
        reason="Vacation",
        approved_by_user_id="USR-MGR-001",
    )
    assert calculate_unpaid_leave_deduction(annual_req, daily_rate_minor=50_000) == 0

