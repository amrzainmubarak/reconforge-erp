"""Versioned native functional-currency voucher and tranche command routes."""

from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import StreamingResponse

from reconforge.api.dependencies import enforce_server_scoped_permissions
from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.procurement_operations import required
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.api.server_identity import request_execution_scope
from reconforge.application.accrual_deferral_evidence import evidence_size, evidence_transport_chunks
from reconforge.auth.models import LocalUser
from reconforge.domain.accrual_deferral import AccrualDeferralPreparation, ScheduleAccounts, ScheduleTranche
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.infrastructure.postgres_accrual_deferral import PostgresAccrualDeferralRepository
from reconforge.infrastructure.postgres_finance_posting import records
from reconforge.platform.common import PlatformError

router = APIRouter(prefix="/accrual-deferral", tags=["accrual-deferral"])
Read = Annotated[LocalUser, Depends(required(frozenset({"accrual_deferral.read", "finance_core.read"})))]
Prepare = Annotated[LocalUser, Depends(required(frozenset({"accrual_deferral.prepare", "finance_core.manage"})))]
Reverse = Annotated[LocalUser, Depends(required(frozenset({"accrual_deferral.prepare", "finance_core.manage", "finance_core.reverse"})))]
Review = Annotated[LocalUser, Depends(required(frozenset({"accrual_deferral.review", "finance_core.validate"})))]
Post = Annotated[LocalUser, Depends(required(frozenset({"accrual_deferral.post", "finance_core.post"})))]
Identifier = Annotated[str, Field(min_length=1, max_length=160)]
Code = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,63}$")]
Day = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Minor = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Accounts(StrictModel):
    prepaid: Code
    expense: Code
    accrued_liability: Code
    cash: Code


class Tranche(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    period_id: Identifier
    posting_date: Day
    weight: Minor
    reversal_period_id: Identifier | None = None
    reversal_date: Day | None = None

    def retained(self) -> ScheduleTranche:
        return ScheduleTranche(self.id, self.period_id, self.posting_date, int(self.weight), self.reversal_period_id, self.reversal_date)


class PreparationRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    reference: Identifier
    mode: Literal["new_prepaid_voucher", "attach_paid_expense", "attach_prepaid_voucher", "expense_accrual"]
    currency_code: Code
    amount_minor: Minor
    journal_code: Code
    period_id: Identifier
    posting_date: Day
    accounts: Accounts
    tranches: list[Tranche] = Field(min_length=1, max_length=36)
    original_effect_id: Identifier | None = None
    reason: str = Field(min_length=1, max_length=500)


class TrancheRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    tranche_id: str = Field(min_length=1, max_length=40)


class ReversalRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    original_plan_id: Identifier
    period_id: Identifier
    posting_date: Day
    reason: str = Field(min_length=1, max_length=500)


class CancellationRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    reason: str = Field(min_length=1, max_length=500)


class PhaseRequest(CancellationRequest):
    expected_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def authority(request: Request, operation: str, *, reverse: bool = False) -> None:
    scope = request_execution_scope(request)
    if not scope.organization_id or not scope.legal_entity_id:
        raise APIError(status_code=403, code="accrual_deferral_entity_scope_required",
            message="Select the explicit native workspace, organization and legal entity for this functional-currency source.")
    finance = {"read": "read", "prepare": "manage", "review": "validate", "post": "post"}[operation]
    permissions = {"accrual_deferral." + operation, "finance_core." + finance}
    if reverse:
        permissions.add("finance_core.reverse")
    for permission in sorted(permissions):
        enforce_server_scoped_permissions(request, permissions=frozenset({permission}), tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id, organization_id=scope.organization_id, entity_id=scope.legal_entity_id)


def execute(request: Request, user: LocalUser,
            operation: Callable[[PostgresAccrualDeferralRepository, PostingActor, FinanceCoreExecutionScope], Any]) -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="accrual_deferral_backend_unavailable", message="Source-owned voucher schedules require PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        try:
            return project(operation(PostgresAccrualDeferralRepository(finance.connection, scope.tenant_id), actor, scope))
        except FinancePostingError as exc:
            status = 413 if "too_large" in exc.code else 403 if "denied" in exc.code else 404 if "not_found" in exc.code else 409 if "conflict" in exc.code else 400
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="accrual_deferral_state_conflict", message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


def project(value: Any, key: str = "") -> Any:
    """Exact API text preserves large native money and allocation weights."""
    if isinstance(value, dict):
        return {field: project(item, field) for field, item in value.items()}
    if isinstance(value, list):
        return [project(item) for item in value]
    return str(value) if type(value) is int and (key.endswith("_minor") or key == "weight") else value


@router.get("/catalog")
def catalog(request: Request, user: Read) -> dict[str, Any]:
    authority(request, "read")

    def collect(repository: PostgresAccrualDeferralRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        scope_data = {"workspace_id": scope.workspace_id, "organization_id": scope.organization_id, "legal_entity_id": scope.legal_entity_id}
        repository._authorize(actor, "read", scope_data)
        connection = repository.connection
        entity = connection.execute("""SELECT e.id,e.entity_code,e.currency_code,o.organization_code FROM reconforge.legal_entities e
            JOIN reconforge.organizations o ON o.tenant_id=e.tenant_id AND o.id=e.organization_id WHERE e.tenant_id=%s
             AND e.id=%s AND e.organization_id=%s AND o.application_workspace_id=%s AND e.active AND o.active""",
            (scope.tenant_id, scope.legal_entity_id, scope.organization_id, scope.workspace_id)).fetchone()
        if entity is None:
            raise APIError(status_code=403, code="accrual_deferral_scope_denied", message="The native functional entity is absent or inactive.")
        return {"schema_version": "accrual-deferral-catalog-v1", "scope": scope_data, "entity": dict(entity),
            "accounts": records(connection.execute("SELECT id,account_code,account_type,chart_id FROM reconforge.finance_accounts WHERE tenant_id=%s AND workspace_id=%s AND active ORDER BY account_code LIMIT 1001",
                (scope.tenant_id, scope.workspace_id))),
            "journals": records(connection.execute("SELECT id,journal_code,chart_id,currency_code FROM reconforge.finance_journals WHERE tenant_id=%s AND workspace_id=%s AND organization_code=%s AND currency_code=%s AND active ORDER BY journal_code LIMIT 201",
                (scope.tenant_id, scope.workspace_id, entity["organization_code"], entity["currency_code"]))),
            "periods": records(connection.execute("SELECT id,name,start_date,end_date,status FROM reconforge.fiscal_periods WHERE tenant_id=%s AND application_workspace_id=%s ORDER BY start_date,id LIMIT 201",
                (scope.tenant_id, scope.workspace_id))),
            "currency_registry_binding": records(connection.execute("SELECT registry_version,registry_digest FROM reconforge.currency_registry_bindings WHERE tenant_id=%s AND workspace_id=%s",
                (scope.tenant_id, scope.workspace_id))), "backend": "postgresql", "statutory_country_packs": 0}

    return execute(request, user, collect)


@router.post("/sources")
def prepare(request: Request, payload: PreparationRequest, user: Prepare) -> dict[str, Any]:
    authority(request, "prepare")

    def create(repository: PostgresAccrualDeferralRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        native = repository.connection.execute("""SELECT e.entity_code,o.organization_code FROM reconforge.legal_entities e
            JOIN reconforge.organizations o ON o.tenant_id=e.tenant_id AND o.id=e.organization_id WHERE e.tenant_id=%s
             AND e.id=%s AND e.organization_id=%s AND o.application_workspace_id=%s""",
            (scope.tenant_id, scope.legal_entity_id, scope.organization_id, scope.workspace_id)).fetchone()
        if native is None:
            raise APIError(status_code=403, code="accrual_deferral_scope_denied", message="The native source hierarchy is absent.")
        retained = AccrualDeferralPreparation(scope.workspace_id, str(scope.organization_id), str(scope.legal_entity_id),
            native["organization_code"], native["entity_code"], payload.reference, payload.mode, payload.currency_code,
            int(payload.amount_minor), payload.journal_code, payload.period_id, payload.posting_date, ScheduleAccounts(**payload.accounts.model_dump()),
            tuple(tranche.retained() for tranche in payload.tranches), payload.reason, payload.original_effect_id)
        return {"plan": repository.prepare_source(retained, command_id=payload.command_id, actor=actor)}

    return execute(request, user, create)


@router.get("/sources")
def sources(request: Request, user: Read, after: str = Query(default="", max_length=160)) -> dict[str, Any]:
    authority(request, "read")
    return execute(request, user, lambda repository, actor, scope: repository.list_sources(workspace_id=scope.workspace_id,
        organization_id=str(scope.organization_id), legal_entity_id=str(scope.legal_entity_id), after=after, actor=actor))


@router.get("/sources/{source_id}")
def source(source_id: str, request: Request, user: Read) -> dict[str, Any]:
    authority(request, "read")
    return execute(request, user, lambda repository, actor, _: {"source": repository.get_source(source_id, actor=actor)})


@router.get("/sources/{source_id}/evidence")
def evidence(source_id: str, request: Request, user: Read) -> dict[str, Any]:
    authority(request, "read")
    return execute(request, user, lambda repository, actor, _: repository.evidence(source_id, actor=actor))


@router.get("/plans/{plan_id}")
def plan(plan_id: str, request: Request, user: Read) -> dict[str, Any]:
    authority(request, "read")
    return execute(request, user, lambda repository, actor, _: {"plan": repository.get_plan(plan_id, actor=actor)})


@router.get("/sources/{source_id}/evidence/export")
def export_evidence(source_id: str, request: Request, user: Read) -> StreamingResponse:
    authority(request, "read")
    retained = execute(request, user, lambda repository, actor, _: repository.evidence(source_id, actor=actor))
    return evidence_response(retained)


def evidence_response(retained: dict[str, Any]) -> StreamingResponse:
    try:
        length = evidence_size(retained)
    except FinancePostingError as exc:
        raise APIError(status_code=413 if "too_large" in exc.code else 400, code=exc.code, message=str(exc)) from exc
    # Authorized immutable capture completes while the scoped connection and
    # source SHARE lock are live; no lazy database work escapes that context.
    return StreamingResponse(evidence_transport_chunks(retained), media_type="application/json",
        headers={"Content-Length": str(length), "Content-Disposition": 'attachment; filename="accrual-deferral-evidence.json"'})


@router.get("/plans/{plan_id}/evidence/export")
def export_plan_evidence(plan_id: str, request: Request, user: Read) -> StreamingResponse:
    authority(request, "read")
    retained = execute(request, user, lambda repository, actor, _: repository.plan_evidence(plan_id, actor=actor))
    return evidence_response(retained)


@router.post("/sources/{source_id}/tranches")
def tranche(source_id: str, request: Request, payload: TrancheRequest, user: Prepare) -> dict[str, Any]:
    authority(request, "prepare")
    return execute(request, user, lambda repository, actor, _: {"plan": repository.prepare_tranche(source_id,
        tranche_id=payload.tranche_id, command_id=payload.command_id, actor=actor)})


@router.post("/sources/{source_id}/reversals")
def reversal(source_id: str, request: Request, payload: ReversalRequest, user: Reverse) -> dict[str, Any]:
    authority(request, "prepare", reverse=True)
    return execute(request, user, lambda repository, actor, _: {"plan": repository.prepare_reversal(source_id,
        original_plan_id=payload.original_plan_id, period_id=payload.period_id, posting_date=payload.posting_date,
        reason=payload.reason, command_id=payload.command_id, actor=actor)})


@router.post("/sources/{source_id}/cancellations")
def cancel(source_id: str, request: Request, payload: CancellationRequest, user: Prepare) -> dict[str, Any]:
    authority(request, "prepare")
    return execute(request, user, lambda repository, actor, _: {"plan": repository.prepare_cancellation(source_id,
        reason=payload.reason, command_id=payload.command_id, actor=actor)})


@router.post("/plans/{plan_id}/review")
def review(plan_id: str, request: Request, payload: PhaseRequest, user: Review) -> dict[str, Any]:
    authority(request, "review")
    return execute(request, user, lambda repository, actor, _: {"plan": repository.review(plan_id,
        expected_plan_digest=payload.expected_plan_digest, reason=payload.reason, command_id=payload.command_id, actor=actor)})


@router.post("/plans/{plan_id}/post")
def post(plan_id: str, request: Request, payload: PhaseRequest, user: Post) -> dict[str, Any]:
    authority(request, "post")
    return execute(request, user, lambda repository, actor, _: {"plan": repository.post(plan_id,
        expected_plan_digest=payload.expected_plan_digest, reason=payload.reason, command_id=payload.command_id, actor=actor)})
