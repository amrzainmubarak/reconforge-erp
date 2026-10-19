"""Exact Employee Leave, Absence Accrual and Self-Service Workflow Invariants.

Enforces integer-scaled entitlement calculations, strict maker-checker segregation
(employees cannot approve their own leave), and atomic balance reservation/restoration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from reconforge.domain.finance_posting import FinancePostingError, text
from reconforge.domain.fixed_assets import exact_minor

LeaveCategory = Literal["Annual", "Sick", "Unpaid", "Parental", "Bereavement"]
LeaveStatus = Literal["Draft", "Submitted", "Approved", "Rejected", "Cancelled"]


class HCMLeaveError(FinancePostingError):
    """Raised when a leave operation violates entitlement, date, or authorization invariants."""


@dataclass(frozen=True)
class LeaveEntitlementBalance:
    employee_id: str
    leave_type: LeaveCategory
    annual_entitlement_days: int
    accrued_days: int
    consumed_days: int

    def __post_init__(self) -> None:
        text(self.employee_id, "employee_id")
        if self.annual_entitlement_days < 0 or self.annual_entitlement_days > 365:
            raise HCMLeaveError("leave_entitlement_invalid", "Annual entitlement must be between 0 and 365 days.")
        if self.accrued_days < 0 or self.consumed_days < 0:
            raise HCMLeaveError("leave_balance_invalid", "Accrued and consumed days must be nonnegative integers.")
        if self.consumed_days > self.accrued_days:
            raise HCMLeaveError("leave_overdrawn", "Consumed leave cannot exceed accrued leave for paid leave categories.")

    @property
    def available_days(self) -> int:
        return self.accrued_days - self.consumed_days


@dataclass(frozen=True)
class LeaveRequest:
    request_id: str
    employee_id: str
    employee_user_id: str
    leave_type: LeaveCategory
    start_date: str
    end_date: str
    requested_days: int
    status: LeaveStatus
    reason: str
    approved_by_user_id: str | None = None
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        text(self.request_id, "request_id")
        text(self.employee_id, "employee_id")
        text(self.employee_user_id, "employee_user_id")
        text(self.reason, "reason", maximum=500)
        if self.rejection_reason is not None:
            text(self.rejection_reason, "rejection_reason", maximum=500)
        if self.requested_days < 1 or self.requested_days > 365:
            raise HCMLeaveError("leave_days_invalid", "Requested days must be between 1 and 365.")
        try:
            start_d = date.fromisoformat(self.start_date)
            end_d = date.fromisoformat(self.end_date)
            if start_d > end_d:
                raise HCMLeaveError("leave_date_reversed", "Start date cannot succeed end date.")
        except ValueError as exc:
            raise HCMLeaveError("leave_date_invalid", f"Invalid leave date format: {exc}") from exc


def accrue_monthly_entitlement(
    balance: LeaveEntitlementBalance,
    completed_months: int,
) -> LeaveEntitlementBalance:
    """Computes exact cumulative leave entitlement based on completed service months."""
    if completed_months < 0 or completed_months > 600:
        raise HCMLeaveError("leave_service_invalid", "Completed service months must be between 0 and 600.")
    # Cumulative integer entitlement: (annual_entitlement * completed_months) // 12
    total_accrued = (balance.annual_entitlement_days * completed_months) // 12
    return LeaveEntitlementBalance(
        employee_id=balance.employee_id,
        leave_type=balance.leave_type,
        annual_entitlement_days=balance.annual_entitlement_days,
        accrued_days=total_accrued,
        consumed_days=balance.consumed_days,
    )


def accrue_prorated_entitlement(
    balance: LeaveEntitlementBalance,
    service_days: int,
    total_year_days: int = 365,
) -> LeaveEntitlementBalance:
    """Computes exact integer day-prorated leave accrual with half-up rounding."""
    if total_year_days <= 0:
        raise HCMLeaveError("leave_year_days_invalid", "Total year days must be positive.")
    if service_days < 0 or service_days > total_year_days:
        raise HCMLeaveError(
            "leave_service_days_invalid",
            f"Service days must be between 0 and total year days ({total_year_days}).",
        )
    # Integer division with deterministic half-up rounding: (annual * service + total // 2) // total
    prorated_accrued = (balance.annual_entitlement_days * service_days + (total_year_days // 2)) // total_year_days
    if prorated_accrued < balance.consumed_days:
        raise HCMLeaveError(
            "leave_overdrawn",
            f"Prorated accrual ({prorated_accrued} days) is less than already consumed leave ({balance.consumed_days} days).",
        )
    return LeaveEntitlementBalance(
        employee_id=balance.employee_id,
        leave_type=balance.leave_type,
        annual_entitlement_days=balance.annual_entitlement_days,
        accrued_days=prorated_accrued,
        consumed_days=balance.consumed_days,
    )


def submit_leave_request(
    request: LeaveRequest,
    balance: LeaveEntitlementBalance,
) -> LeaveRequest:
    """Submits a leave request, checking available balance for paid categories."""
    if request.leave_type != "Unpaid" and request.requested_days > balance.available_days:
        raise HCMLeaveError(
            "leave_insufficient_balance",
            f"Insufficient leave balance: available {balance.available_days} days, requested {request.requested_days} days."
        )
    return LeaveRequest(
        request_id=request.request_id,
        employee_id=request.employee_id,
        employee_user_id=request.employee_user_id,
        leave_type=request.leave_type,
        start_date=request.start_date,
        end_date=request.end_date,
        requested_days=request.requested_days,
        status="Submitted",
        reason=request.reason,
        approved_by_user_id=None,
        rejection_reason=None,
    )


def approve_leave_request(
    request: LeaveRequest,
    balance: LeaveEntitlementBalance,
    approver_user_id: str,
) -> tuple[LeaveRequest, LeaveEntitlementBalance]:
    """Approves a leave request enforcing strict SoD (no self-approval) and deducts balance."""
    if request.status != "Submitted":
        raise HCMLeaveError("leave_not_submitted", f"Only submitted requests can be approved; current: {request.status}")

    # Strict Maker-Checker segregation
    if approver_user_id == request.employee_user_id:
        raise HCMLeaveError(
            "leave_self_approval_prohibited",
            "Segregation of Duties violation: employees are prohibited from approving their own leave requests."
        )

    if request.leave_type != "Unpaid" and request.requested_days > balance.available_days:
        raise HCMLeaveError(
            "leave_insufficient_balance",
            f"Cannot approve: requested {request.requested_days} days exceeds available {balance.available_days} days."
        )

    new_consumed = balance.consumed_days + (request.requested_days if request.leave_type != "Unpaid" else 0)
    updated_balance = LeaveEntitlementBalance(
        employee_id=balance.employee_id,
        leave_type=balance.leave_type,
        annual_entitlement_days=balance.annual_entitlement_days,
        accrued_days=balance.accrued_days,
        consumed_days=new_consumed,
    )

    approved_request = LeaveRequest(
        request_id=request.request_id,
        employee_id=request.employee_id,
        employee_user_id=request.employee_user_id,
        leave_type=request.leave_type,
        start_date=request.start_date,
        end_date=request.end_date,
        requested_days=request.requested_days,
        status="Approved",
        reason=request.reason,
        approved_by_user_id=text(approver_user_id, "approver_user_id"),
        rejection_reason=None,
    )

    return approved_request, updated_balance


def reject_leave_request(
    request: LeaveRequest,
    balance: LeaveEntitlementBalance,
    rejector_user_id: str,
    reason: str,
) -> LeaveRequest:
    """Rejects a submitted leave request enforcing maker-checker SoD and preserving balance."""
    if request.status != "Submitted":
        raise HCMLeaveError(
            "leave_not_submitted",
            f"Only submitted requests can be rejected; current: {request.status}",
        )
    if balance.employee_id != request.employee_id:
        raise HCMLeaveError(
            "leave_balance_mismatch",
            f"Leave balance employee '{balance.employee_id}' does not match request '{request.employee_id}'.",
        )
    clean_rejector = text(rejector_user_id, "rejector_user_id")
    if clean_rejector == request.employee_user_id:
        raise HCMLeaveError(
            "leave_self_rejection_prohibited",
            "Segregation of Duties violation: employees cannot review or reject their own leave requests.",
        )
    clean_reason = text(reason, "rejection_reason", maximum=500)

    # Balance is strictly preserved (unconsumed)
    return LeaveRequest(
        request_id=request.request_id,
        employee_id=request.employee_id,
        employee_user_id=request.employee_user_id,
        leave_type=request.leave_type,
        start_date=request.start_date,
        end_date=request.end_date,
        requested_days=request.requested_days,
        status="Rejected",
        reason=request.reason,
        approved_by_user_id=None,
        rejection_reason=clean_reason,
    )


def withdraw_leave_request(request: LeaveRequest) -> LeaveRequest:
    """Withdraws a draft or submitted leave request prior to managerial review."""
    if request.status not in ("Draft", "Submitted"):
        raise HCMLeaveError(
            "leave_withdraw_invalid",
            f"Only draft or submitted requests can be withdrawn; current status: {request.status}",
        )
    return LeaveRequest(
        request_id=request.request_id,
        employee_id=request.employee_id,
        employee_user_id=request.employee_user_id,
        leave_type=request.leave_type,
        start_date=request.start_date,
        end_date=request.end_date,
        requested_days=request.requested_days,
        status="Cancelled",
        reason=request.reason,
        approved_by_user_id=request.approved_by_user_id,
        rejection_reason=request.rejection_reason,
    )


def cancel_leave_request(
    request: LeaveRequest,
    balance: LeaveEntitlementBalance,
    current_date: str,
) -> tuple[LeaveRequest, LeaveEntitlementBalance]:
    """Cancels an approved leave request before its start date, restoring consumed balance."""
    if request.status != "Approved":
        raise HCMLeaveError("leave_cancel_invalid", f"Only approved requests can be cancelled; current: {request.status}")

    curr_d = date.fromisoformat(current_date)
    start_d = date.fromisoformat(request.start_date)
    if curr_d >= start_d:
        raise HCMLeaveError(
            "leave_already_started",
            f"Cannot cancel leave on or after start date {request.start_date}; requires retro adjustment."
        )

    restored_consumed = balance.consumed_days - (request.requested_days if request.leave_type != "Unpaid" else 0)
    updated_balance = LeaveEntitlementBalance(
        employee_id=balance.employee_id,
        leave_type=balance.leave_type,
        annual_entitlement_days=balance.annual_entitlement_days,
        accrued_days=balance.accrued_days,
        consumed_days=restored_consumed,
    )

    cancelled_request = LeaveRequest(
        request_id=request.request_id,
        employee_id=request.employee_id,
        employee_user_id=request.employee_user_id,
        leave_type=request.leave_type,
        start_date=request.start_date,
        end_date=request.end_date,
        requested_days=request.requested_days,
        status="Cancelled",
        reason=request.reason,
        approved_by_user_id=request.approved_by_user_id,
        rejection_reason=request.rejection_reason,
    )

    return cancelled_request, updated_balance


def rollover_leave_entitlement(
    balance: LeaveEntitlementBalance,
    max_carryover_days: int,
) -> tuple[LeaveEntitlementBalance, int]:
    """Rollovers unused leave balance to the next period with carryover cap and forfeiture calculation."""
    if max_carryover_days < 0 or max_carryover_days > 365:
        raise HCMLeaveError("leave_carryover_invalid", "Max carryover days must be between 0 and 365.")

    available = balance.available_days
    carried_over_days = min(available, max_carryover_days)
    forfeited_days = max(0, available - max_carryover_days)

    new_balance = LeaveEntitlementBalance(
        employee_id=balance.employee_id,
        leave_type=balance.leave_type,
        annual_entitlement_days=balance.annual_entitlement_days,
        accrued_days=carried_over_days,
        consumed_days=0,
    )
    return new_balance, forfeited_days


def calculate_unpaid_leave_deduction(
    request: LeaveRequest,
    daily_rate_minor: int,
) -> int:
    """Calculates integer minor-unit payroll deduction for approved unpaid absence."""
    exact_minor(daily_rate_minor, "daily_rate_minor", zero=True)
    if request.leave_type != "Unpaid":
        return 0
    return request.requested_days * daily_rate_minor

