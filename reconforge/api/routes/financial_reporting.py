"""Current-authority PostgreSQL opening and classified statement API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_permission
from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.operational_finance import _authority as _source_authority
from reconforge.api.server_finance_core import (
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.api.server_identity import request_execution_scope
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.financial_reporting import AccountClassification, OpeningLine, OpeningPreparation, ReportingScope
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository

router = APIRouter(prefix="/financial-reporting", tags=["financial-reporting"])
Read = Annotated[Any, Depends(require_permission("finance_core.read"))]
Manage = Annotated[Any, Depends(require_permission("finance_core.manage"))]
Review = Annotated[Any, Depends(require_permission("finance_core.validate"))]
Post = Annotated[Any, Depends(require_permission("finance_core.post"))]


class ClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    account_code: str = Field(min_length=1, max_length=64)
    section: str = Field(min_length=1, max_length=32)
    is_cash: bool = False


class MappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    name: str = Field(min_length=1, max_length=160)
    accounts: list[ClassificationRequest] = Field(min_length=1, max_length=1000)


class OpeningLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    account_code: str = Field(min_length=1, max_length=64)
    debit_minor: str = Field(pattern=r"^(0|[1-9][0-9]{0,18})$")
    credit_minor: str = Field(pattern=r"^(0|[1-9][0-9]{0,18})$")


class OpeningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    map_id: str = Field(min_length=1, max_length=160)
    period_id: str = Field(min_length=1, max_length=160)
    journal_code: str = Field(min_length=1, max_length=64)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(min_length=1, max_length=500)
    lines: list[OpeningLineRequest] = Field(min_length=2, max_length=64)


class PhaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(min_length=1, max_length=140)
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


def project(value: Any, key: str = "") -> Any:
    """Exact monetary strings at every nested JS boundary; counts remain integers."""
    if isinstance(value, dict):
        return {field: project(item, field) for field, item in value.items()}
    if isinstance(value, list):
        return [project(item) for item in value]
    if type(value) is int and key.endswith("_minor"):
        return str(value)
    return value


def _authority(request: Request, permission: str, value: dict[str, Any] | None = None, *, audit: bool = True) -> None:
    """Classifications and read reports have scope, without an opening command amount."""
    if value is not None:
        scope = request_execution_scope(request)
        if any(
            value[key] != expected
            for key, expected in (
                ("workspace_id", scope.workspace_id),
                ("organization_id", scope.organization_id),
                ("legal_entity_id", scope.legal_entity_id),
            )
        ):
            raise APIError(
                status_code=403,
                code="financial_reporting_scope_denied",
                message="Reporting evidence is outside selected authority.",
            )
    _source_authority(
        request, permission, value if value is not None and "amount_minor" in value else None, audit=audit
    )


def _execute(request: Request, user: Any, operation: Any) -> dict[str, Any]:
    if not server_finance_core_enabled(request):
        raise APIError(
            status_code=503,
            code="financial_reporting_backend_unavailable",
            message="Financial statements require the PostgreSQL server profile.",
        )
    actor = _actor(request, user)

    def run(finance: Any, scope: Any) -> dict[str, Any]:
        try:
            repository = PostgresFinancialReportingRepository(finance.connection, scope.tenant_id)
            value = operation(repository, actor, scope)
            return {"api_contract_version": "financial-reporting-api-v1", **project(value)}
        except FinancePostingError as exc:
            status = (
                404
                if exc.code.endswith("not_found")
                else 403
                if exc.code.endswith("denied")
                or exc.code in {"posting_human_required", "posting_step_up_required", "posting_permission_denied"}
                else 409
                if exc.code.endswith(("conflict", "review_invalid", "unmapped"))
                else 400
            )
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, run)


def _scope(value: Any) -> ReportingScope:
    if not value.organization_id or not value.legal_entity_id:
        raise APIError(
            status_code=403, code="financial_reporting_scope_denied", message="Select an organization and legal entity."
        )
    return ReportingScope(value.workspace_id, value.organization_id, value.legal_entity_id)


@router.get("/catalog")
def catalog(request: Request, current_user: Read) -> dict[str, Any]:
    _authority(request, "finance_core.read")
    return _execute(
        request,
        current_user,
        lambda repository, actor, scope: {"catalog": repository.catalog(_scope(scope), actor=actor)},
    )


@router.get("/maps")
def maps(request: Request, current_user: Read) -> dict[str, Any]:
    _authority(request, "finance_core.read")
    return _execute(
        request,
        current_user,
        lambda repository, actor, scope: {"maps": repository.list_maps(_scope(scope), actor=actor)},
    )


@router.get("/openings")
def openings(request: Request, current_user: Read) -> dict[str, Any]:
    _authority(request, "finance_core.read")
    return _execute(
        request,
        current_user,
        lambda repository, actor, scope: {"openings": repository.list_openings(_scope(scope), actor=actor)},
    )


@router.post("/maps")
def prepare_map(request: Request, payload: MappingRequest, current_user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.manage")

    def run(repository: Any, actor: Any, scope: Any) -> dict[str, Any]:
        value = repository.prepare_map(
            _scope(scope),
            name=payload.name,
            accounts=[AccountClassification(**line.model_dump()) for line in payload.accounts],
            command_id=payload.command_id,
            actor=actor,
        )
        _authority(request, "finance_core.manage", value, audit=False)
        return {"map": value}

    return _execute(request, current_user, run)


@router.post("/maps/{map_id}/review")
def review_map(request: Request, map_id: str, payload: PhaseRequest, current_user: Review) -> dict[str, Any]:
    _authority(request, "finance_core.validate")

    def run(repository: Any, actor: Any, scope: Any) -> dict[str, Any]:
        retained = repository.get_map(map_id, actor=actor)
        _authority(request, "finance_core.validate", retained)
        return {"map": repository.review_map(map_id, **payload.model_dump(), actor=actor)}

    return _execute(request, current_user, run)


@router.post("/openings")
def prepare_opening(request: Request, payload: OpeningRequest, current_user: Manage) -> dict[str, Any]:
    _authority(request, "finance_core.manage")

    def run(repository: Any, actor: Any, scope: Any) -> dict[str, Any]:
        value = repository.prepare_opening(
            OpeningPreparation(
                _scope(scope),
                payload.map_id,
                scope.organization_code,
                scope.entity_code,
                payload.period_id,
                payload.journal_code,
                payload.posting_date,
                payload.reason,
                tuple(
                    OpeningLine(line.account_code, int(line.debit_minor), int(line.credit_minor))
                    for line in payload.lines
                ),
            ),
            command_id=payload.command_id,
            actor=actor,
        )
        _authority(request, "finance_core.manage", value, audit=False)
        return {"opening": value}

    return _execute(request, current_user, run)


@router.post("/openings/{opening_id}/review")
def review_opening(request: Request, opening_id: str, payload: PhaseRequest, current_user: Review) -> dict[str, Any]:
    _authority(request, "finance_core.validate")

    def run(repository: Any, actor: Any, scope: Any) -> dict[str, Any]:
        retained = repository.get_opening(opening_id, actor=actor)
        _authority(request, "finance_core.validate", retained)
        return {"opening": repository.review_opening(opening_id, **payload.model_dump(), actor=actor)}

    return _execute(request, current_user, run)


@router.post("/openings/{opening_id}/post")
def post_opening(request: Request, opening_id: str, payload: PhaseRequest, current_user: Post) -> dict[str, Any]:
    _authority(request, "finance_core.post")

    def run(repository: Any, actor: Any, scope: Any) -> dict[str, Any]:
        retained = repository.get_opening(opening_id, actor=actor)
        _authority(request, "finance_core.post", retained)
        return {"opening": repository.post_opening(opening_id, **payload.model_dump(), actor=actor)}

    return _execute(request, current_user, run)


@router.get("/statements")
def statements(request: Request, current_user: Read, map_id: str, period_id: str, as_of_date: str) -> dict[str, Any]:
    _authority(request, "finance_core.read")

    def run(repository: Any, actor: Any, scope: Any) -> dict[str, Any]:
        value = repository.report(
            map_id=map_id,
            period_id=period_id,
            as_of_date=as_of_date,
            organization_code=scope.organization_code,
            entity_code=scope.entity_code,
            actor=actor,
        )
        _authority(request, "finance_core.read", value)
        return {"statements": value}

    return _execute(request, current_user, run)
