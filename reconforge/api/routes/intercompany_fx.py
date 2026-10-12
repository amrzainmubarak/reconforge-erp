"""Strict paired foreign trade API, bound to current whole organization authority."""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import enforce_server_scoped_permissions
from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.fixed_assets import project
from reconforge.api.routes.procurement_operations import required
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.api.server_identity import request_execution_scope
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.intercompany_fx import (
    GroupAccounts,
    GroupBook,
    IntercompanyFxPreparation,
    PartyAccounts,
    PartyBook,
)
from reconforge.domain.operational_fx_tax import HistoricalRate
from reconforge.infrastructure.postgres_finance_posting import records
from reconforge.infrastructure.postgres_intercompany_fx import PostgresIntercompanyFxRepository
from reconforge.platform.common import PlatformError, current_server_principal

router = APIRouter(prefix="/intercompany-fx", tags=["intercompany-fx"])
Read = Annotated[LocalUser, Depends(required(frozenset({"intercompany_fx.read", "finance_core.read"}))) ]
Prepare = Annotated[LocalUser, Depends(required(frozenset({"intercompany_fx.prepare", "finance_core.manage"}))) ]
Reverse = Annotated[LocalUser, Depends(required(frozenset({"intercompany_fx.prepare", "finance_core.manage", "finance_core.reverse"}))) ]
Review = Annotated[LocalUser, Depends(required(frozenset({"intercompany_fx.review", "finance_core.validate"}))) ]
Post = Annotated[LocalUser, Depends(required(frozenset({"intercompany_fx.post", "finance_core.post"}))) ]
Identifier = Annotated[str, Field(min_length=1, max_length=160)]
Code = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,63}$")]
Day = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Rate(StrictModel):
    rate: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,12})?$")
    source: str = Field(min_length=1, max_length=160)
    effective_at: str = Field(min_length=20, max_length=40)

    def retained(self) -> HistoricalRate:
        return HistoricalRate(**self.model_dump())


class PartyMap(StrictModel):
    party: Code
    trade: Code
    cash: Code
    realized_gain: Code
    realized_loss: Code
    unrealized_gain: Code
    unrealized_loss: Code


class GroupMap(StrictModel):
    receivable: Code
    payable: Code
    revenue: Code
    expense: Code
    cash: Code
    realized_gain: Code
    realized_loss: Code
    unrealized_gain: Code
    unrealized_loss: Code
    cta: Code


class Party(StrictModel):
    legal_entity_id: Identifier
    journal_code: Code
    period_id: Identifier
    accounts: PartyMap


class Adjustment(StrictModel):
    legal_entity_id: Identifier
    journal_code: Code
    period_id: Identifier
    accounts: GroupMap


class PreparationRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    reference: Identifier
    transaction_currency_code: Code
    transaction_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    posting_date: Day
    seller: Party
    buyer: Party
    adjustment: Adjustment
    seller_original_rate: Rate
    buyer_original_rate: Rate
    reason: str = Field(min_length=1, max_length=500)


class Periods(StrictModel):
    seller: Identifier
    buyer: Identifier
    adjustment: Identifier


class PartyRates(StrictModel):
    seller: Rate
    buyer: Rate


class ProgressRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    period_ids: Periods
    posting_date: Day
    reason: str = Field(min_length=1, max_length=500)


class SettlementRequest(ProgressRequest):
    transaction_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    rates: PartyRates


class RevaluationRequest(ProgressRequest):
    rates: PartyRates


class ReversalRequest(ProgressRequest):
    original_revaluation_id: Identifier


class IncomeRates(StrictModel):
    seller: dict[Day, Rate] = Field(min_length=1, max_length=64)
    buyer: dict[Day, Rate] = Field(min_length=1, max_length=64)


class EliminationRequest(ProgressRequest):
    closing_rates: PartyRates
    income_rates: IncomeRates


class PhaseRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    expected_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


def authority(request: Request, operation: str) -> None:
    scope = request_execution_scope(request)
    if not scope.organization_id or scope.legal_entity_id is not None:
        raise APIError(status_code=403, code="intercompany_fx_organization_scope_required",
            message="Select the workspace and organization for the explicitly authorized three-entity group.")
    finance = {"read": "read", "prepare": "manage", "review": "validate", "post": "post"}[operation]
    for permission in ("intercompany_fx." + operation, "finance_core." + finance):
        enforce_server_scoped_permissions(request, permissions=frozenset({permission}), tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id, organization_id=scope.organization_id)


def execute(request: Request, user: LocalUser,
            operation: Callable[[PostgresIntercompanyFxRepository, PostingActor, FinanceCoreExecutionScope], Any]) -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="intercompany_fx_backend_unavailable", message="Source-owned paired foreign trade requires PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        try:
            return project(operation(PostgresIntercompanyFxRepository(finance.connection, scope.tenant_id), actor, scope))
        except FinancePostingError as exc:
            status = 403 if "denied" in exc.code else 404 if "not_found" in exc.code else 409 if "conflict" in exc.code else 400
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="intercompany_fx_state_conflict", message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.get("/catalog")
def catalog(request: Request, user: Read) -> dict[str, Any]:
    authority(request, "read")

    def collect(repository: PostgresIntercompanyFxRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        principal = current_server_principal()
        if principal is None:
            raise APIError(status_code=403, code="intercompany_fx_actor_denied", message="A current human identity is required.")
        entities = records(repository.connection.execute("""SELECT id,entity_code,name,currency_code FROM reconforge.legal_entities
            WHERE tenant_id=%s AND organization_id=%s AND active AND id=ANY(%s) ORDER BY entity_code LIMIT 101""",
            (scope.tenant_id, scope.organization_id, sorted(principal.authorized_legal_entity_ids))))
        if len(entities) > 100:
            raise APIError(status_code=400, code="intercompany_fx_catalog_limit", message="Select at most 100 entity scopes.")
        return {"catalog": {"entities": entities, "accounts": repository.owner.finance.list_accounts(workspace=scope.workspace_id),
            "journals": repository.owner.finance.list_journals(workspace=scope.workspace_id, organization_code=scope.organization_code),
            "currencies": records(repository.connection.execute("SELECT code,name,minor_units FROM reconforge.currencies WHERE tenant_id=%s AND active ORDER BY code LIMIT 1000", (scope.tenant_id,))),
            "periods": records(repository.connection.execute("SELECT id,name,status,start_date,end_date FROM reconforge.fiscal_periods WHERE tenant_id=%s AND application_workspace_id=%s ORDER BY start_date,id LIMIT 100", (scope.tenant_id, scope.workspace_id)))}}

    return execute(request, user, collect)


@router.post("/sources")
def prepare(request: Request, payload: PreparationRequest, user: Prepare) -> dict[str, Any]:
    authority(request, "prepare")

    def invoke(repository: PostgresIntercompanyFxRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        ids = [getattr(payload, book).legal_entity_id for book in ("seller", "buyer", "adjustment")]
        entities = records(repository.connection.execute("SELECT id,entity_code,currency_code FROM reconforge.legal_entities WHERE tenant_id=%s AND organization_id=%s AND id=ANY(%s)",
            (scope.tenant_id, scope.organization_id, ids)))
        by_id = {row["id"]: row for row in entities}
        if len(ids) != len(set(ids)) or len(by_id) != 3:
            raise APIError(status_code=403, code="intercompany_fx_scope_denied", message="Three distinct authorized entity scopes are required.")
        def party_book(cfg: Party) -> PartyBook:
            master = by_id[cfg.legal_entity_id]
            return PartyBook(cfg.legal_entity_id, master["entity_code"], master["currency_code"], cfg.journal_code, cfg.period_id,
                PartyAccounts(**cfg.accounts.model_dump()))

        cfg = payload.adjustment
        master = by_id[cfg.legal_entity_id]
        adjustment = GroupBook(cfg.legal_entity_id, master["entity_code"], master["currency_code"], cfg.journal_code, cfg.period_id,
            GroupAccounts(**cfg.accounts.model_dump()))
        original = IntercompanyFxPreparation(scope.workspace_id, str(scope.organization_id), str(scope.organization_code), payload.reference,
            payload.transaction_currency_code, int(payload.transaction_minor), payload.posting_date,
            party_book(payload.seller), party_book(payload.buyer), adjustment,
            seller_original_rate=payload.seller_original_rate.retained(), buyer_original_rate=payload.buyer_original_rate.retained(), reason=payload.reason)
        return {"plan": repository.prepare(original, command_id=payload.command_id, actor=actor)}

    return execute(request, user, invoke)


@router.get("/sources")
def sources(request: Request, user: Read, after: str = Query(default="", max_length=160)) -> dict[str, Any]:
    authority(request, "read")
    return execute(request, user, lambda repository, actor, scope: {"sources": repository.list_sources(workspace_id=scope.workspace_id,
        organization_id=str(scope.organization_id), after=after, actor=actor)})


@router.get("/sources/{source_id}")
def source(request: Request, source_id: str, user: Read) -> dict[str, Any]:
    authority(request, "read")
    return execute(request, user, lambda repository, actor, scope: {"source": repository.get_source(source_id, actor=actor)})


def progress(payload: ProgressRequest) -> dict[str, Any]:
    return {"command_id": payload.command_id, "period_ids": payload.period_ids.model_dump(), "posting_date": payload.posting_date, "reason": payload.reason}


@router.post("/sources/{source_id}/settlements")
def settlement(request: Request, source_id: str, payload: SettlementRequest, user: Prepare) -> dict[str, Any]:
    authority(request, "prepare")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.prepare_settlement(source_id,
        transaction_minor=int(payload.transaction_minor), rates={book: getattr(payload.rates, book).retained() for book in ("seller", "buyer")}, actor=actor, **progress(payload))})


@router.post("/sources/{source_id}/revaluations")
def revaluation(request: Request, source_id: str, payload: RevaluationRequest, user: Prepare) -> dict[str, Any]:
    authority(request, "prepare")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.prepare_revaluation(source_id,
        rates={book: getattr(payload.rates, book).retained() for book in ("seller", "buyer")}, actor=actor, **progress(payload))})


@router.post("/sources/{source_id}/revaluation-reversals")
def reversal(request: Request, source_id: str, payload: ReversalRequest, user: Reverse) -> dict[str, Any]:
    authority(request, "prepare")
    scope = request_execution_scope(request)
    enforce_server_scoped_permissions(request, permissions=frozenset({"finance_core.reverse"}), tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id, organization_id=scope.organization_id)
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.prepare_revaluation_reversal(source_id,
        original_revaluation_id=payload.original_revaluation_id, actor=actor, **progress(payload))})


@router.post("/sources/{source_id}/eliminations")
def elimination(request: Request, source_id: str, payload: EliminationRequest, user: Prepare) -> dict[str, Any]:
    authority(request, "prepare")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.prepare_elimination(source_id,
        closing_rates={book: getattr(payload.closing_rates, book).retained() for book in ("seller", "buyer")},
        income_rates={book: {day: rate.retained() for day, rate in getattr(payload.income_rates, book).items()} for book in ("seller", "buyer")}, actor=actor, **progress(payload))})


@router.get("/plans/{plan_id}")
def plan(request: Request, plan_id: str, user: Read) -> dict[str, Any]:
    authority(request, "read")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.get_plan(plan_id, actor=actor)})


@router.post("/plans/{plan_id}/review")
def review(request: Request, plan_id: str, payload: PhaseRequest, user: Review) -> dict[str, Any]:
    authority(request, "review")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.review(plan_id, actor=actor, **payload.model_dump())})


@router.post("/plans/{plan_id}/post")
def post(request: Request, plan_id: str, payload: PhaseRequest, user: Post) -> dict[str, Any]:
    authority(request, "post")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.post(plan_id, actor=actor, **payload.model_dump())})


@router.get("/plans/{plan_id}/evidence")
def evidence(request: Request, plan_id: str, user: Read) -> dict[str, Any]:
    authority(request, "read")
    return execute(request, user, lambda repository, actor, scope: {"evidence": repository.evidence(plan_id, actor=actor)})


@router.get("/sources/{source_id}/report")
def report(request: Request, source_id: str, user: Read) -> dict[str, Any]:
    authority(request, "read")
    return execute(request, user, lambda repository, actor, scope: {"report": repository.report(source_id, actor=actor)})
