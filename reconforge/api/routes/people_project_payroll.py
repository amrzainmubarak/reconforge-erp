"""Scoped nonstatutory workforce operations with an internal private DB gate."""
from collections.abc import Callable
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.operational_finance import _authority
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.api.server_personnel import execute_postgres_personnel_scoped
from reconforge.application.people_project_payroll import PeopleProjectPayrollService
from reconforge.auth.models import LocalUser
from reconforge.domain.budget_control import BudgetControlError
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.people_project_payroll import (
    EmployeeRegistration,
    EmploymentAgreement,
    PeopleScope,
    TimeLine,
    TimeSubmission,
    minor_text,
)
from reconforge.infrastructure.postgres_people_project_payroll import PostgresPeopleProjectPayrollRepository

router = APIRouter(prefix="/people-project-payroll", tags=["people-project-payroll"])
Read = Annotated[LocalUser, Depends(require_permission("people_project_payroll.read"))]
Sensitive = Annotated[LocalUser, Depends(require_permission("people_project_payroll.read_sensitive"))]
Personnel = Annotated[LocalUser, Depends(require_permission("people_project_payroll.personnel"))]
Manage = Annotated[LocalUser, Depends(require_permission("people_project_payroll.manage"))]
Approve = Annotated[LocalUser, Depends(require_permission("people_project_payroll.approve_time"))]
Prepare = Annotated[LocalUser, Depends(require_permission("people_project_payroll.prepare"))]
Review = Annotated[LocalUser, Depends(require_permission("people_project_payroll.review"))]
Post = Annotated[LocalUser, Depends(require_permission("people_project_payroll.post"))]
Pay = Annotated[LocalUser, Depends(require_permission("people_project_payroll.pay"))]
Minor = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)


class EmployeeRequest(Command):
    employee_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._/-]{0,63}$")
    display_name: str = Field(min_length=1, max_length=160)
    linked_user_id: str | None = Field(default=None, min_length=1, max_length=160)


class EmploymentRequest(Command):
    valid_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    valid_through: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    hourly_rate_minor: Minor
    currency_code: str = Field(pattern=r"^[A-Z]{3}$")
    reason: str = Field(min_length=1, max_length=500)


class ProjectRequest(Command):
    project_code: str = Field(min_length=1, max_length=64)
    dimension_code: str = Field(min_length=1, max_length=64)
    value_code: str = Field(min_length=1, max_length=64)


class Interval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    project_id: str = Field(min_length=1, max_length=160)
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=1, le=1440)


class TimeRequest(Command):
    employee_id: str = Field(min_length=1, max_length=160)
    business_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    lines: list[Interval] = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)


class ApprovalRequest(Command):
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class PayrunRequest(Command):
    time_ids: list[str] = Field(min_length=1, max_length=1000)
    budget_id: str = Field(min_length=1, max_length=160)
    expected_budget_version: int = Field(ge=1)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    journal_code: str = Field(min_length=1, max_length=64)
    expense_account_code: str = Field(min_length=1, max_length=64)
    liability_account_code: str = Field(min_length=1, max_length=64)
    cash_account_code: str = Field(min_length=1, max_length=64)


class PaymentRequest(Command):
    employees_minor: dict[str, Minor] = Field(min_length=1, max_length=100)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class PhaseRequest(Command):
    expected_plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def project(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {field: project(item, "amount_minor" if key in {"project_minor", "employees_minor"} else field) for field, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [project(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value) if type(value) is int and key.endswith("_minor") else value


def people_scope(scope: FinanceCoreExecutionScope) -> PeopleScope:
    return PeopleScope(scope.workspace_id, str(scope.organization_id), str(scope.legal_entity_id), scope.organization_code, scope.entity_code)


def execute(request: Request, user: LocalUser, *, permission: str, private: bool,
            operation: Callable[[PostgresPeopleProjectPayrollRepository, PostingActor, FinanceCoreExecutionScope], Any]) -> Any:
    _authority(request, permission)
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="people_backend_unavailable", message="Nonstatutory workforce accounting requires PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        try:
            repository = PostgresPeopleProjectPayrollRepository(finance.connection, scope.tenant_id, require_live_session_assurance=True)
            return project(operation(repository, actor, scope))
        except FinancePostingError as exc:
            status = 403 if "denied" in exc.code else 404 if "not_found" in exc.code else 409 if "conflict" in exc.code else 400
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
        except BudgetControlError as exc:
            raise APIError(status_code=409, code="people_budget_conflict", message="The original budget or its current authority conflicts with this command.") from exc
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"23503", "23505", "23514", "40001", "40P01"}:
                raise APIError(status_code=409, code="people_source_conflict", message="The retained workforce source conflicts with this command; reload before retrying.") from None
            raise

    # The server operation chooses its factory; no HTTP field selects a DB role.
    helper = execute_postgres_personnel_scoped if private else execute_postgres_finance_core_scoped
    return helper(request, invoke)


@router.post("/employees")
def register_employee(request: Request, payload: EmployeeRequest, user: Personnel) -> Any:
    return execute(request, user, permission="people_project_payroll.personnel", private=True, operation=lambda repo, actor, scope:
        {"employee": repo.register_employee(EmployeeRegistration(people_scope(scope), payload.employee_code, payload.display_name, payload.linked_user_id), command_id=payload.command_id, actor=actor)})


@router.post("/employees/{employee_id}/employment")
def employ(request: Request, employee_id: str, payload: EmploymentRequest, user: Personnel) -> Any:
    return execute(request, user, permission="people_project_payroll.personnel", private=True, operation=lambda repo, actor, scope:
        {"employment": repo.employ(EmploymentAgreement(employee_id, payload.valid_from, payload.valid_through, minor_text(payload.hourly_rate_minor, positive=True), payload.currency_code, payload.reason), command_id=payload.command_id, actor=actor)})


@router.post("/projects")
def register_project(request: Request, payload: ProjectRequest, user: Manage) -> Any:
    return execute(request, user, permission="people_project_payroll.manage", private=False, operation=lambda repo, actor, scope:
        {"project": repo.register_project(people_scope(scope), project_code=payload.project_code, dimension_code=payload.dimension_code, value_code=payload.value_code, command_id=payload.command_id, actor=actor)})


@router.post("/times")
def submit_time(request: Request, payload: TimeRequest, user: Manage) -> Any:
    return execute(request, user, permission="people_project_payroll.manage", private=False, operation=lambda repo, actor, scope:
        {"time": repo.submit_time(TimeSubmission(payload.employee_id, payload.business_date, tuple(TimeLine(**line.model_dump()) for line in payload.lines), payload.reason), command_id=payload.command_id, actor=actor)})


@router.post("/times/{time_id}/approve")
def approve_time(request: Request, time_id: str, payload: ApprovalRequest, user: Approve) -> Any:
    return execute(request, user, permission="people_project_payroll.approve_time", private=False, operation=lambda repo, actor, scope:
        {"time": repo.approve_time(time_id, expected_digest=payload.expected_digest, command_id=payload.command_id, actor=actor)})


@router.post("/payruns")
def prepare_payrun(request: Request, payload: PayrunRequest, user: Prepare) -> Any:
    return execute(request, user, permission="people_project_payroll.prepare", private=True, operation=lambda repo, actor, scope:
        {"plan": repo.prepare_payrun(people_scope(scope), **payload.model_dump(exclude={"command_id"}), command_id=payload.command_id, actor=actor)})


@router.post("/payruns/{payrun_id}/payments")
def prepare_payment(request: Request, payrun_id: str, payload: PaymentRequest, user: Pay) -> Any:
    return execute(request, user, permission="people_project_payroll.pay", private=True, operation=lambda repo, actor, scope:
        {"plan": repo.prepare_payment(payrun_id, employees_minor={key: minor_text(value, positive=True) for key, value in payload.employees_minor.items()}, period_id=payload.period_id, posting_date=payload.posting_date, command_id=payload.command_id, actor=actor)})


@router.post("/plans/{plan_id}/review")
def review(request: Request, plan_id: str, payload: PhaseRequest, user: Review) -> Any:
    return execute(request, user, permission="people_project_payroll.review", private=True, operation=lambda repo, actor, scope:
        {"plan": PeopleProjectPayrollService(repo).financial_phase("review", plan_id, expected_plan_digest=payload.expected_plan_digest, command_id=payload.command_id, actor=actor)})


@router.post("/plans/{plan_id}/post")
def post(request: Request, plan_id: str, payload: PhaseRequest, user: Post) -> Any:
    return execute(request, user, permission="people_project_payroll.post", private=True, operation=lambda repo, actor, scope:
        {"plan": PeopleProjectPayrollService(repo).financial_phase("post", plan_id, expected_plan_digest=payload.expected_plan_digest, command_id=payload.command_id, actor=actor)})


@router.post("/payruns/{payrun_id}/cancel")
def cancel(request: Request, payrun_id: str, payload: PhaseRequest, user: Prepare) -> Any:
    return execute(request, user, permission="people_project_payroll.prepare", private=True, operation=lambda repo, actor, scope:
        {"plan": PeopleProjectPayrollService(repo).financial_phase("cancel", payrun_id, expected_plan_digest=payload.expected_plan_digest, command_id=payload.command_id, actor=actor)})


@router.get("/plans/{plan_id}")
def get_plan(request: Request, plan_id: str, user: Read) -> Any:
    return execute(request, user, permission="people_project_payroll.read", private=False, operation=lambda repo, actor, scope: {"plan": repo.get(plan_id, actor=actor)})


@router.get("/plans/{plan_id}/private")
def get_private_plan(request: Request, plan_id: str, user: Sensitive) -> Any:
    return execute(request, user, permission="people_project_payroll.read_sensitive", private=True, operation=lambda repo, actor, scope: {"plan": repo.get(plan_id, actor=actor, sensitive=True)})


@router.get("/payruns/{payrun_id}/evidence")
def evidence(request: Request, payrun_id: str, user: Sensitive) -> Any:
    return execute(request, user, permission="people_project_payroll.read_sensitive", private=True, operation=lambda repo, actor, scope: repo.evidence(payrun_id, actor=actor))


@router.get("/catalog/{kind}")
def catalog(request: Request, kind: Literal["employees", "employment", "projects", "times", "payruns", "payments"], user: Read,
            after: str = Query(default="", max_length=160), limit: int = Query(default=25, ge=1, le=100)) -> Any:
    return execute(request, user, permission="people_project_payroll.read", private=False, operation=lambda repo, actor, scope:
        repo.catalog(kind, people_scope(scope), after=after, limit=limit, actor=actor))
