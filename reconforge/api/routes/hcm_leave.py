"""FastAPI routes for HCM Employee Leave, Entitlements, and Maker-Checker Approvals."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.errors import APIError
from reconforge.auth.models import LocalUser
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

router = APIRouter(prefix="/hcm/leave", tags=["hcm-leave"])
Read = Annotated[LocalUser, Depends(require_permission("people_project_payroll.personnel"))]
Manage = Annotated[LocalUser, Depends(require_permission("people_project_payroll.manage"))]
Approve = Annotated[LocalUser, Depends(require_permission("people_project_payroll.approve_time"))]


def _repo(request: Request) -> tuple[SqliteHCMLeaveRepository, str]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
    conn = sqlite3.connect(db_path)
    workspace_id = getattr(request.state, "workspace_id", "default")
    return SqliteHCMLeaveRepository(conn), workspace_id


class EntitlementBalancePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    employee_id: str = Field(min_length=1, max_length=64)
    leave_type: Literal["Annual", "Sick", "Unpaid", "Parental", "Bereavement"]
    annual_entitlement_days: int = Field(ge=0, le=365)
    accrued_days: int = Field(ge=0, le=365)
    consumed_days: int = Field(default=0, ge=0, le=365)


class LeaveRequestSubmissionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=1, max_length=64)
    employee_id: str = Field(min_length=1, max_length=64)
    leave_type: Literal["Annual", "Sick", "Unpaid", "Parental", "Bereavement"]
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    requested_days: int = Field(ge=1, le=365)
    reason: str = Field(min_length=1, max_length=500)


class LeaveRejectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rejection_reason: str = Field(min_length=1, max_length=500)


class LeaveCancellationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    current_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/balances")
def set_entitlement_balance(
    user: Manage, payload: EntitlementBalancePayload, request: Request
) -> dict[str, object]:
    repo, ws_id = _repo(request)
    try:
        balance = LeaveEntitlementBalance(
            employee_id=payload.employee_id,
            leave_type=payload.leave_type,
            annual_entitlement_days=payload.annual_entitlement_days,
            accrued_days=payload.accrued_days,
            consumed_days=payload.consumed_days,
        )
        repo.save_balance(ws_id, balance)
    except HCMLeaveError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

    return {
        "status": "success",
        "employee_id": balance.employee_id,
        "leave_type": balance.leave_type,
        "available_days": balance.available_days,
    }


@router.get("/balances/{employee_id}/{leave_type}")
def get_entitlement_balance(
    user: Read, employee_id: str, leave_type: str, request: Request
) -> dict[str, object]:
    repo, ws_id = _repo(request)
    balance = repo.get_balance(ws_id, employee_id, leave_type)
    if not balance:
        raise APIError(
            status_code=404,
            code="leave_balance_not_found",
            message=f"Balance not found for employee {employee_id} and leave type {leave_type}",
        )
    return {
        "employee_id": balance.employee_id,
        "leave_type": balance.leave_type,
        "annual_entitlement_days": balance.annual_entitlement_days,
        "accrued_days": balance.accrued_days,
        "consumed_days": balance.consumed_days,
        "available_days": balance.available_days,
    }


@router.post("/requests")
def submit_request(
    user: Read, payload: LeaveRequestSubmissionPayload, request: Request
) -> dict[str, object]:
    repo, ws_id = _repo(request)
    balance = repo.get_balance(ws_id, payload.employee_id, payload.leave_type)
    if not balance:
        raise APIError(
            status_code=400,
            code="leave_balance_missing",
            message=f"No entitlement balance found for employee {payload.employee_id} and leave type {payload.leave_type}",
        )

    leave_req = LeaveRequest(
        request_id=payload.request_id,
        employee_id=payload.employee_id,
        employee_user_id=user.username,
        leave_type=payload.leave_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        requested_days=payload.requested_days,
        status="Draft",
        reason=payload.reason,
    )

    try:
        submitted = submit_leave_request(leave_req, balance)
        repo.save_request(ws_id, submitted)
    except HCMLeaveError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

    return {
        "status": "success",
        "request_id": submitted.request_id,
        "leave_status": submitted.status,
    }


@router.get("/requests/{request_id}")
def get_request(user: Read, request_id: str, request: Request) -> dict[str, object]:
    repo, ws_id = _repo(request)
    leave_req = repo.get_request(ws_id, request_id)
    if not leave_req:
        raise APIError(
            status_code=404,
            code="leave_request_not_found",
            message=f"Leave request {request_id} not found",
        )
    return {
        "request_id": leave_req.request_id,
        "employee_id": leave_req.employee_id,
        "employee_user_id": leave_req.employee_user_id,
        "leave_type": leave_req.leave_type,
        "start_date": leave_req.start_date,
        "end_date": leave_req.end_date,
        "requested_days": leave_req.requested_days,
        "status": leave_req.status,
        "reason": leave_req.reason,
        "approved_by_user_id": leave_req.approved_by_user_id,
        "rejection_reason": leave_req.rejection_reason,
    }


@router.post("/requests/{request_id}/approve")
def approve_request(user: Approve, request_id: str, request: Request) -> dict[str, object]:
    repo, ws_id = _repo(request)
    leave_req = repo.get_request(ws_id, request_id)
    if not leave_req:
        raise APIError(
            status_code=404,
            code="leave_request_not_found",
            message=f"Leave request {request_id} not found",
        )

    balance = repo.get_balance(ws_id, leave_req.employee_id, leave_req.leave_type)
    if not balance:
        raise APIError(
            status_code=400,
            code="leave_balance_missing",
            message="No balance found to execute leave deduction",
        )

    try:
        approved, updated_balance = approve_leave_request(
            leave_req, balance, approver_user_id=user.username
        )
        repo.save_request(ws_id, approved)
        repo.save_balance(ws_id, updated_balance)
    except HCMLeaveError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

    return {
        "status": "success",
        "request_id": approved.request_id,
        "leave_status": approved.status,
        "approved_by": approved.approved_by_user_id,
        "remaining_available_days": updated_balance.available_days,
    }


@router.post("/requests/{request_id}/reject")
def reject_request(
    user: Approve, request_id: str, payload: LeaveRejectionPayload, request: Request
) -> dict[str, object]:
    repo, ws_id = _repo(request)
    leave_req = repo.get_request(ws_id, request_id)
    if not leave_req:
        raise APIError(
            status_code=404,
            code="leave_request_not_found",
            message=f"Leave request {request_id} not found",
        )

    balance = repo.get_balance(ws_id, leave_req.employee_id, leave_req.leave_type)
    if not balance:
        raise APIError(
            status_code=400,
            code="leave_balance_missing",
            message="No balance found for leave request validation",
        )

    try:
        rejected = reject_leave_request(
            leave_req,
            balance,
            rejector_user_id=user.username,
            reason=payload.rejection_reason,
        )
        repo.save_request(ws_id, rejected)
    except HCMLeaveError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

    return {
        "status": "success",
        "request_id": rejected.request_id,
        "leave_status": rejected.status,
        "rejection_reason": rejected.rejection_reason,
    }


@router.post("/requests/{request_id}/cancel")
def cancel_request(
    user: Manage, request_id: str, payload: LeaveCancellationPayload, request: Request
) -> dict[str, object]:
    repo, ws_id = _repo(request)
    leave_req = repo.get_request(ws_id, request_id)
    if not leave_req:
        raise APIError(
            status_code=404,
            code="leave_request_not_found",
            message=f"Leave request {request_id} not found",
        )

    balance = repo.get_balance(ws_id, leave_req.employee_id, leave_req.leave_type)
    if not balance:
        raise APIError(
            status_code=400,
            code="leave_balance_missing",
            message="No balance found for cancellation restitution",
        )

    try:
        cancelled, restored_balance = cancel_leave_request(
            leave_req, balance, current_date=payload.current_date
        )
        repo.save_request(ws_id, cancelled)
        repo.save_balance(ws_id, restored_balance)
    except HCMLeaveError as exc:
        raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

    return {
        "status": "success",
        "request_id": cancelled.request_id,
        "leave_status": cancelled.status,
        "restored_available_days": restored_balance.available_days,
    }
