"""Tests for HCM Leave entitlement, balance deduction, SoD enforcement, and cancellation."""

import pytest

from reconforge.domain.hcm_leave import (
    HCMLeaveError,
    LeaveEntitlementBalance,
    LeaveRequest,
    accrue_monthly_entitlement,
    approve_leave_request,
    cancel_leave_request,
    submit_leave_request,
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
