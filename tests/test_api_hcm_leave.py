"""Level 2 integration tests for HCM Employee Leave API schemas and SQLite repository."""

import sqlite3

import pytest
from pydantic import ValidationError

from reconforge.api.routes.hcm_leave import (
    EntitlementBalancePayload,
    LeaveCancellationPayload,
    LeaveRejectionPayload,
    LeaveRequestSubmissionPayload,
)
from reconforge.domain.hcm_leave import (
    HCMLeaveError,
    LeaveEntitlementBalance,
    LeaveRequest,
    approve_leave_request,
    cancel_leave_request,
    reject_leave_request,
    submit_leave_request,
)
from reconforge.infrastructure.sqlite_hcm_leave import SqliteHCMLeaveRepository


def test_hcm_leave_schema_strictness() -> None:
    valid_balance = {
        "employee_id": "EMP-001",
        "leave_type": "Annual",
        "annual_entitlement_days": 30,
        "accrued_days": 15,
        "consumed_days": 5,
    }
    bal = EntitlementBalancePayload.model_validate(valid_balance)
    assert bal.employee_id == "EMP-001"
    assert bal.annual_entitlement_days == 30

    # Reject negative or excessive days
    with pytest.raises(ValidationError):
        EntitlementBalancePayload.model_validate({**valid_balance, "annual_entitlement_days": -1})
    with pytest.raises(ValidationError):
        EntitlementBalancePayload.model_validate({**valid_balance, "annual_entitlement_days": 400})

    valid_req = {
        "request_id": "REQ-001",
        "employee_id": "EMP-001",
        "leave_type": "Annual",
        "start_date": "2026-11-01",
        "end_date": "2026-11-05",
        "requested_days": 5,
        "reason": "Annual family vacation",
    }
    req = LeaveRequestSubmissionPayload.model_validate(valid_req)
    assert req.requested_days == 5

    # Reject invalid date format
    with pytest.raises(ValidationError):
        LeaveRequestSubmissionPayload.model_validate({**valid_req, "start_date": "01-11-2026"})

    with pytest.raises(ValidationError):
        LeaveRejectionPayload.model_validate({"rejection_reason": ""})

    with pytest.raises(ValidationError):
        LeaveCancellationPayload.model_validate({"current_date": "bad-date"})


def test_sqlite_hcm_leave_repository_lifecycle() -> None:
    conn = sqlite3.connect(":memory:")
    repo = SqliteHCMLeaveRepository(conn)
    ws_id = "ws_default"

    balance = LeaveEntitlementBalance(
        employee_id="EMP-10",
        leave_type="Annual",
        annual_entitlement_days=30,
        accrued_days=20,
        consumed_days=5,
    )
    repo.save_balance(ws_id, balance)

    retrieved_bal = repo.get_balance(ws_id, "EMP-10", "Annual")
    assert retrieved_bal is not None
    assert retrieved_bal.available_days == 15

    # Create & submit leave request
    leave_req = LeaveRequest(
        request_id="REQ-101",
        employee_id="EMP-10",
        employee_user_id="alice",
        leave_type="Annual",
        start_date="2026-12-01",
        end_date="2026-12-05",
        requested_days=5,
        status="Draft",
        reason="Family holiday",
    )
    submitted = submit_leave_request(leave_req, retrieved_bal)
    repo.save_request(ws_id, submitted)

    retrieved_req = repo.get_request(ws_id, "REQ-101")
    assert retrieved_req is not None
    assert retrieved_req.status == "Submitted"

    # Enforce Maker-Checker: alice cannot approve her own request
    with pytest.raises(HCMLeaveError) as exc_info:
        approve_leave_request(retrieved_req, retrieved_bal, approver_user_id="alice")
    assert "Segregation of Duties" in str(exc_info.value)

    # Manager bob approves the request
    approved, updated_bal = approve_leave_request(
        retrieved_req, retrieved_bal, approver_user_id="bob"
    )
    assert approved.status == "Approved"
    assert approved.approved_by_user_id == "bob"
    assert updated_bal.consumed_days == 10
    assert updated_bal.available_days == 10

    repo.save_request(ws_id, approved)
    repo.save_balance(ws_id, updated_bal)

    # Cancel before start date restores consumed balance
    cancelled, restored_bal = cancel_leave_request(
        approved, updated_bal, current_date="2026-11-20"
    )
    assert cancelled.status == "Cancelled"
    assert restored_bal.consumed_days == 5
    assert restored_bal.available_days == 15

    repo.save_request(ws_id, cancelled)
    repo.save_balance(ws_id, restored_bal)

    # Verify requests listing
    requests = repo.list_requests(ws_id, "EMP-10")
    assert len(requests) == 1
    assert requests[0].status == "Cancelled"

    # Second request: tested for rejection
    req2 = LeaveRequest(
        request_id="REQ-102",
        employee_id="EMP-10",
        employee_user_id="alice",
        leave_type="Annual",
        start_date="2026-12-10",
        end_date="2026-12-12",
        requested_days=2,
        status="Draft",
        reason="Short break",
    )
    sub2 = submit_leave_request(req2, restored_bal)
    rejected2 = reject_leave_request(
        sub2, restored_bal, rejector_user_id="bob", reason="Blackout period during year-end audit."
    )
    assert rejected2.status == "Rejected"
    assert rejected2.rejection_reason == "Blackout period during year-end audit."
    repo.save_request(ws_id, rejected2)

    retrieved2 = repo.get_request(ws_id, "REQ-102")
    assert retrieved2 is not None
    assert retrieved2.status == "Rejected"
