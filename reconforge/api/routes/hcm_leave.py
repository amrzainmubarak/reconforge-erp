"""FastAPI routes for HCM Employee Leave, Entitlements, and Maker-Checker Approvals."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import enforce_server_scoped_permissions, require_permission
from reconforge.api.enterprise_scope import enterprise_transaction
from reconforge.api.errors import APIError
from reconforge.auth import LocalAuthService
from reconforge.auth.models import LocalUser
from reconforge.domain.hcm_leave import (
    HCMLeaveError,
    LeaveEntitlementBalance,
    LeaveRequest,
    accrue_prorated_entitlement,
    approve_leave_request,
    calculate_unpaid_leave_deduction,
    cancel_leave_request,
    reject_leave_request,
    rollover_leave_entitlement,
    submit_leave_request,
    withdraw_leave_request,
)
from reconforge.infrastructure.postgres_hcm_leave import PostgresHCMLeaveRepository
from reconforge.infrastructure.sqlite_hcm_leave import SqliteHCMLeaveRepository
from reconforge.platform.common import ServerPrincipal

router = APIRouter(prefix="/hcm/leave", tags=["hcm-leave"])
Read = Annotated[LocalUser, Depends(require_permission("people_project_payroll.personnel"))]
Manage = Annotated[LocalUser, Depends(require_permission("people_project_payroll.manage"))]
Approve = Annotated[LocalUser, Depends(require_permission("people_project_payroll.approve_time"))]


def _can_read_other_employee(
    request: Request, repo: SqliteHCMLeaveRepository | PostgresHCMLeaveRepository, user: LocalUser, workspace_id: str,
) -> bool:
    """Additional HR authority is checked against current authenticated grants."""
    permissions = frozenset({"people_project_payroll.manage", "people_project_payroll.approve_time"})
    principal = getattr(request.state, "server_principal", None)
    if isinstance(principal, ServerPrincipal):
        if not permissions & principal.permissions:
            return False
        enforce_server_scoped_permissions(
            request, permissions=permissions, tenant_id=request.state.tenant_id,
            workspace_id=workspace_id, organization_id=getattr(request.state, "organization_id", None),
            entity_id=getattr(request.state, "legal_entity_id", None),
        )
        if isinstance(repo, PostgresHCMLeaveRepository):
            _pin_server_authority(request, repo, user, workspace_id, permissions, "any")
        return True
    if isinstance(repo, SqliteHCMLeaveRepository):
        return bool(permissions & LocalAuthService(repo.connection).roles.user_permissions(user.username))
    return False


def _require_personal_employee(
    repo: SqliteHCMLeaveRepository | PostgresHCMLeaveRepository,
    workspace_id: str, employee_id: str, user: LocalUser,
) -> None:
    if not repo.employee_is_linked_to(workspace_id, employee_id, user.id):
        raise APIError(status_code=403, code="leave_employee_forbidden", message="The employee is not linked to the authenticated user.")


def _require_request_reader(
    request: Request, repo: SqliteHCMLeaveRepository | PostgresHCMLeaveRepository,
    workspace_id: str, leave_req: LeaveRequest, user: LocalUser,
) -> None:
    if _can_read_other_employee(request, repo, user, workspace_id):
        return
    _require_personal_employee(repo, workspace_id, leave_req.employee_id, user)


def _require_review_owner(
    repo: SqliteHCMLeaveRepository | PostgresHCMLeaveRepository,
    workspace_id: str, leave_req: LeaveRequest, user: LocalUser, *, action: str,
) -> None:
    owner_id = repo.employee_identity_id(workspace_id, leave_req.employee_id)
    if owner_id is None:
        raise APIError(status_code=403, code="leave_employee_forbidden", message="A canonical employee identity is required for review.")
    if owner_id == user.id:
        raise APIError(status_code=400, code=f"leave_self_{action}_prohibited", message="Independent employee review is required.")


@contextmanager
def _repo(
    request: Request, *, user: LocalUser, permissions: frozenset[str],
    permission_mode: Literal["all", "any"] = "all", mutation: bool = False,
) -> Iterator[tuple[SqliteHCMLeaveRepository | PostgresHCMLeaveRepository, str]]:
    with enterprise_transaction(request, permissions=permissions, permission_mode=permission_mode, require_hierarchy=True) as business:
        if business is not None:
            connection = business.connection
            repository = PostgresHCMLeaveRepository(connection, business.scope.tenant_id)
            _pin_server_authority(request, repository, user, business.scope.workspace_id, permissions, permission_mode)
            if mutation:
                with repository.mutation():
                    yield repository, business.scope.workspace_id
            else:
                yield repository, business.scope.workspace_id
            return
        db_path = getattr(request.app.state, "db_path", None)
        if db_path is None:
            raise APIError(status_code=500, code="db_not_configured", message="API database path is not configured.")
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        try:
            local_repository = SqliteHCMLeaveRepository(connection)
            workspace_id = getattr(request.state, "workspace_id", "default")
            if mutation:
                with local_repository.mutation():
                    _recheck_local_authority(connection, user, permissions, permission_mode)
                    yield local_repository, workspace_id
            else:
                connection.execute("BEGIN")
                _recheck_local_authority(connection, user, permissions, permission_mode)
                yield local_repository, workspace_id
        finally:
            connection.close()


def _recheck_local_authority(
    connection: sqlite3.Connection, user: LocalUser, permissions: frozenset[str], permission_mode: Literal["all", "any"],
) -> None:
    """Read current authority inside the same writer/snapshot as the operation."""
    service = LocalAuthService(connection)
    current = service.users.get_by_username(user.username)
    if current is None or current.disabled or current.id != user.id:
        raise APIError(status_code=403, code="permission_denied", message="Permission denied.")
    granted = service.roles.user_permissions(user.username)
    if not (permissions <= granted if permission_mode == "all" else bool(permissions & granted)):
        raise APIError(status_code=403, code="permission_denied", message="Permission denied.")


def _pin_server_authority(
    request: Request, repo: PostgresHCMLeaveRepository, user: LocalUser, workspace_id: str,
    permissions: frozenset[str], permission_mode: Literal["all", "any"],
) -> None:
    """Existing native admission pins actual authority until the business commit."""
    admitted = False
    for permission in sorted(permissions):
        try:
            with repo.connection.transaction():
                repo.connection.execute("SELECT reconforge.hc_actor(%s,%s,%s,%s,%s,%s)", (
                    repo.tenant_id, workspace_id, request.state.organization_id, request.state.legal_entity_id,
                    user.id, permission,
                ))
        except Exception as exc:
            if getattr(exc, "sqlstate", None) != "23514":
                raise
            if permission_mode == "all":
                raise APIError(status_code=403, code="permission_denied", message="Permission denied.") from None
        else:
            admitted = True
            if permission_mode == "any":
                break
    if not admitted:
        raise APIError(status_code=403, code="permission_denied", message="Permission denied.")


class EntitlementBalancePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    employee_id: str = Field(min_length=1, max_length=64)
    employee_user_id: str | None = Field(
        default=None, min_length=1, max_length=160,
        description="Existing active identity ID, explicitly provisioned by a manager; enterprise identities must match the canonical employee.",
    )
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
    with _repo(request, user=user, mutation=True, permissions=frozenset({'people_project_payroll.manage'}), permission_mode="all") as ((repo, ws_id)):
        if isinstance(repo, PostgresHCMLeaveRepository) and not repo.employee_is_in_scope(ws_id, payload.employee_id):
            raise APIError(status_code=403, code="leave_employee_forbidden", message="The employee is outside the selected canonical scope.")
        try:
            if payload.employee_user_id is not None:
                if isinstance(repo, PostgresHCMLeaveRepository):
                    if not repo.employee_is_linked_to(ws_id, payload.employee_id, payload.employee_user_id):
                        raise HCMLeaveError("leave_employee_identity_conflict", "The identity must match the canonical employee linkage.")
                else:
                    repo.bind_employee(ws_id, payload.employee_id, payload.employee_user_id)
            balance = LeaveEntitlementBalance(
                employee_id=payload.employee_id,
                leave_type=payload.leave_type,
                annual_entitlement_days=payload.annual_entitlement_days,
                accrued_days=payload.accrued_days,
                consumed_days=payload.consumed_days,
            )
            repo.save_balance(ws_id, balance)
            repo.record_action(ws_id, balance.employee_id, "leave_balance_set", actor_user_id=user.id, actor_label=user.username)
        except HCMLeaveError as exc:
            raise APIError(status_code=409 if exc.code == "leave_employee_identity_conflict" else 400, code=exc.code, message=str(exc)) from exc

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
    with _repo(request, user=user, permissions=frozenset({'people_project_payroll.personnel'}), permission_mode="all") as ((repo, ws_id)):
        if not _can_read_other_employee(request, repo, user, ws_id):
            _require_personal_employee(repo, ws_id, employee_id, user)
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
    with _repo(request, user=user, mutation=True, permissions=frozenset({'people_project_payroll.personnel'}), permission_mode="all") as ((repo, ws_id)):
        _require_personal_employee(repo, ws_id, payload.employee_id, user)
        if repo.get_request(ws_id, payload.request_id) is not None:
            raise APIError(status_code=409, code="leave_request_exists", message="A leave request with this identifier already exists.")
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
            employee_user_id=user.id,
            leave_type=payload.leave_type,
            start_date=payload.start_date,
            end_date=payload.end_date,
            requested_days=payload.requested_days,
            status="Draft",
            reason=payload.reason,
        )

        try:
            submitted = submit_leave_request(leave_req, balance)
            repo.save_request(ws_id, submitted, create_only=True)
            repo.record_action(ws_id, submitted.request_id, "leave_submitted", actor_user_id=user.id, actor_label=user.username)
        except HCMLeaveError as exc:
            raise APIError(status_code=409 if exc.code == "leave_request_exists" else 400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "request_id": submitted.request_id,
            "leave_status": submitted.status,
        }


@router.get("/requests/{request_id}")
def get_request(user: Read, request_id: str, request: Request) -> dict[str, object]:
    with _repo(request, user=user, permissions=frozenset({'people_project_payroll.personnel'}), permission_mode="all") as ((repo, ws_id)):
        leave_req = repo.get_request(ws_id, request_id)
        if not leave_req:
            raise APIError(
                status_code=404,
                code="leave_request_not_found",
                message=f"Leave request {request_id} not found",
            )
        _require_request_reader(request, repo, ws_id, leave_req, user)
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
    with _repo(request, user=user, mutation=True, permissions=frozenset({'people_project_payroll.approve_time'}), permission_mode="all") as ((repo, ws_id)):
        leave_req = repo.get_request(ws_id, request_id)
        if not leave_req:
            raise APIError(
                status_code=404,
                code="leave_request_not_found",
                message=f"Leave request {request_id} not found",
            )

        _require_review_owner(repo, ws_id, leave_req, user, action="approval")
        balance = repo.get_balance(ws_id, leave_req.employee_id, leave_req.leave_type)
        if not balance:
            raise APIError(
                status_code=400,
                code="leave_balance_missing",
                message="No balance found to execute leave deduction",
            )

        try:
            approved, updated_balance = approve_leave_request(
                leave_req, balance, approver_user_id=user.id
            )
            repo.save_request(ws_id, approved)
            repo.save_balance(ws_id, updated_balance)
            repo.record_action(ws_id, approved.request_id, "leave_approved", actor_user_id=user.id, actor_label=user.username)
        except HCMLeaveError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "request_id": approved.request_id,
            "leave_status": approved.status,
            "approved_by": user.username,
            "approved_by_user_id": approved.approved_by_user_id,
            "remaining_available_days": updated_balance.available_days,
        }


@router.post("/requests/{request_id}/reject")
def reject_request(
    user: Approve, request_id: str, payload: LeaveRejectionPayload, request: Request
) -> dict[str, object]:
    with _repo(request, user=user, mutation=True, permissions=frozenset({'people_project_payroll.approve_time'}), permission_mode="all") as ((repo, ws_id)):
        leave_req = repo.get_request(ws_id, request_id)
        if not leave_req:
            raise APIError(
                status_code=404,
                code="leave_request_not_found",
                message=f"Leave request {request_id} not found",
            )

        _require_review_owner(repo, ws_id, leave_req, user, action="rejection")
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
                rejector_user_id=user.id,
                reason=payload.rejection_reason,
            )
            repo.save_request(ws_id, rejected)
            repo.record_action(ws_id, rejected.request_id, "leave_rejected", actor_user_id=user.id, actor_label=user.username)
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
    with _repo(request, user=user, mutation=True, permissions=frozenset({'people_project_payroll.manage'}), permission_mode="all") as ((repo, ws_id)):
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
            repo.record_action(ws_id, cancelled.request_id, "leave_cancelled", actor_user_id=user.id, actor_label=user.username)
        except HCMLeaveError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "request_id": cancelled.request_id,
            "leave_status": cancelled.status,
            "restored_available_days": restored_balance.available_days,
        }


class LeaveRolloverPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_carryover_days: int = Field(ge=0, le=365)


class ProratedAccrualPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    service_days: int = Field(ge=0, le=366)
    total_year_days: int = Field(ge=365, le=366)


class UnpaidDeductionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    daily_rate_minor: int = Field(ge=0)


@router.post("/requests/{request_id}/withdraw")
def withdraw_request(user: Read, request_id: str, request: Request) -> dict[str, object]:
    """Self-service withdrawal of draft or submitted leave requests."""
    with _repo(request, user=user, mutation=True, permissions=frozenset({'people_project_payroll.personnel'}), permission_mode="all") as ((repo, ws_id)):
        leave_req = repo.get_request(ws_id, request_id)
        if not leave_req:
            raise APIError(
                status_code=404,
                code="leave_request_not_found",
                message=f"Leave request {request_id} not found",
            )
        _require_personal_employee(repo, ws_id, leave_req.employee_id, user)
        try:
            withdrawn = withdraw_leave_request(leave_req)
            repo.save_request(ws_id, withdrawn)
            repo.record_action(ws_id, withdrawn.request_id, "leave_withdrawn", actor_user_id=user.id, actor_label=user.username)
        except HCMLeaveError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "request_id": withdrawn.request_id,
            "leave_status": withdrawn.status,
        }


@router.post("/balances/{employee_id}/{leave_type}/rollover")
def rollover_balance(
    user: Manage, employee_id: str, leave_type: str, payload: LeaveRolloverPayload, request: Request
) -> dict[str, object]:
    """Fiscal year-end rollover of leave balance with carryover cap and forfeiture calculation."""
    with _repo(request, user=user, mutation=True, permissions=frozenset({'people_project_payroll.manage'}), permission_mode="all") as ((repo, ws_id)):
        balance = repo.get_balance(ws_id, employee_id, leave_type)
        if not balance:
            raise APIError(
                status_code=404,
                code="leave_balance_not_found",
                message=f"Leave balance for employee {employee_id} and type {leave_type} not found",
            )
        try:
            new_balance, forfeited_days = rollover_leave_entitlement(balance, payload.max_carryover_days)
            repo.save_balance(ws_id, new_balance)
            repo.record_action(ws_id, new_balance.employee_id, "leave_balance_rolled_over", actor_user_id=user.id, actor_label=user.username)
        except HCMLeaveError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "employee_id": new_balance.employee_id,
            "leave_type": new_balance.leave_type,
            "carried_over_days": new_balance.accrued_days,
            "forfeited_days": forfeited_days,
            "available_days": new_balance.available_days,
        }


@router.post("/balances/{employee_id}/{leave_type}/accrue-prorated")
def accrue_prorated(
    user: Manage, employee_id: str, leave_type: str, payload: ProratedAccrualPayload, request: Request
) -> dict[str, object]:
    """Accrue prorated entitlement based on exact completed service days."""
    with _repo(request, user=user, mutation=True, permissions=frozenset({'people_project_payroll.manage'}), permission_mode="all") as ((repo, ws_id)):
        balance = repo.get_balance(ws_id, employee_id, leave_type)
        if not balance:
            raise APIError(
                status_code=404,
                code="leave_balance_not_found",
                message=f"Leave balance for employee {employee_id} and type {leave_type} not found",
            )
        try:
            updated_balance = accrue_prorated_entitlement(
                balance,
                service_days=payload.service_days,
                total_year_days=payload.total_year_days,
            )
            repo.save_balance(ws_id, updated_balance)
            repo.record_action(ws_id, updated_balance.employee_id, "leave_balance_accrued", actor_user_id=user.id, actor_label=user.username)
        except HCMLeaveError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "employee_id": updated_balance.employee_id,
            "leave_type": updated_balance.leave_type,
            "accrued_days": updated_balance.accrued_days,
            "available_days": updated_balance.available_days,
        }


@router.post("/requests/{request_id}/unpaid-deduction")
def compute_unpaid_deduction(
    user: Read, request_id: str, payload: UnpaidDeductionPayload, request: Request
) -> dict[str, object]:
    """Compute unpaid leave wage deduction using exact minor arithmetic."""
    with _repo(request, user=user, permissions=frozenset({'people_project_payroll.personnel'}), permission_mode="all") as ((repo, ws_id)):
        leave_req = repo.get_request(ws_id, request_id)
        if not leave_req:
            raise APIError(
                status_code=404,
                code="leave_request_not_found",
                message=f"Leave request {request_id} not found",
            )
        _require_request_reader(request, repo, ws_id, leave_req, user)
        try:
            deduction_minor = calculate_unpaid_leave_deduction(leave_req, daily_rate_minor=payload.daily_rate_minor)
        except HCMLeaveError as exc:
            raise APIError(status_code=400, code=exc.code, message=str(exc)) from exc

        return {
            "status": "success",
            "request_id": leave_req.request_id,
            "unpaid_leave_days": leave_req.requested_days if leave_req.leave_type == "Unpaid" else 0,
            "deduction_minor": deduction_minor,
        }
