"""Strict organization-bound native intercompany pairs and group evidence."""

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
from reconforge.domain.intercompany_operations import IntercompanyPreparation
from reconforge.infrastructure.postgres_finance_posting import records
from reconforge.infrastructure.postgres_intercompany_operations import PostgresIntercompanyOperationsRepository
from reconforge.platform.common import PlatformError, current_server_principal

router = APIRouter(prefix="/intercompany-operations", tags=["intercompany-operations"])
Read = Annotated[LocalUser, Depends(required(frozenset({"intercompany_operations.read", "finance_core.read"})))]
Prepare = Annotated[LocalUser, Depends(required(frozenset({"intercompany_operations.prepare", "finance_core.manage"})))]
Review = Annotated[LocalUser, Depends(required(frozenset({"intercompany_operations.review", "finance_core.validate"})))]
Post = Annotated[LocalUser, Depends(required(frozenset({"intercompany_operations.post", "finance_core.post"})))]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PreparationRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    seller_entity_id: str = Field(min_length=1, max_length=160)
    buyer_entity_id: str = Field(min_length=1, max_length=160)
    adjustment_entity_id: str = Field(min_length=1, max_length=160)
    reference: str = Field(min_length=1, max_length=160)
    amount_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    journal_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
    receivable_account_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
    payable_account_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
    revenue_account_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
    expense_account_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
    cash_account_code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
    reason: str = Field(min_length=1, max_length=500)


class SettlementRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    amount_minor: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(min_length=1, max_length=500)


class EliminationRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    period_id: str = Field(min_length=1, max_length=160)
    posting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(min_length=1, max_length=500)


class PhaseRequest(StrictModel):
    command_id: str = Field(min_length=1, max_length=140)
    expected_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


def authority(request: Request, operation: str) -> None:
    scope = request_execution_scope(request)
    if not scope.organization_id or scope.legal_entity_id is not None:
        raise APIError(status_code=403, code="intercompany_organization_scope_required",
                       message="Select the organization/workspace context for an explicitly authorized multi-entity operation.")
    finance = {"read": "read", "prepare": "manage", "review": "validate", "post": "post"}[operation]
    for permission in ("intercompany_operations." + operation, "finance_core." + finance):
        enforce_server_scoped_permissions(request, permissions=frozenset({permission}), tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id, organization_id=scope.organization_id)


def execute(request: Request, user: LocalUser,
            operation: Callable[[PostgresIntercompanyOperationsRepository, PostingActor, FinanceCoreExecutionScope], Any]) -> Any:
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="intercompany_backend_unavailable", message="Native paired intercompany posting requires PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> Any:
        try:
            return project(operation(PostgresIntercompanyOperationsRepository(finance.connection, scope.tenant_id), actor, scope))
        except FinancePostingError as exc:
            status = 403 if "denied" in exc.code else 404 if "not_found" in exc.code else 409 if "conflict" in exc.code else 400
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
        except PlatformError as exc:
            raise APIError(status_code=409, code="intercompany_state_conflict", message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.get("/catalog")
def catalog(request: Request, user: Read) -> dict[str, Any]:
    authority(request, "read")

    def collect(repository: PostgresIntercompanyOperationsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        principal = current_server_principal()
        if principal is None:
            raise APIError(status_code=403, code="intercompany_actor_denied", message="A current human identity is required.")
        entities = records(repository.connection.execute("""SELECT id,entity_code,name,currency_code FROM reconforge.legal_entities
            WHERE tenant_id=%s AND organization_id=%s AND active AND id=ANY(%s) ORDER BY entity_code LIMIT 101""",
            (scope.tenant_id, scope.organization_id, sorted(principal.authorized_legal_entity_ids))))
        if len(entities) > 100:
            raise APIError(status_code=400, code="intercompany_catalog_limit", message="Select a bounded organization containing at most100 entity scopes.")
        return {"catalog": {"entities": entities,
            "accounts": repository.owner.finance.list_accounts(workspace=scope.workspace_id),
            "journals": repository.owner.finance.list_journals(workspace=scope.workspace_id, organization_code=scope.organization_code),
            "periods": records(repository.connection.execute("SELECT id,name,status,start_date,end_date FROM reconforge.fiscal_periods WHERE tenant_id=%s AND application_workspace_id=%s ORDER BY start_date,id LIMIT 100", (scope.tenant_id, scope.workspace_id))),
            "maps": records(repository.connection.execute("""SELECT m.id,m.legal_entity_id,m.payload->>'name' AS name
                FROM reconforge.financial_reporting_maps m JOIN reconforge.financial_reporting_map_reviews r
                ON r.tenant_id=m.tenant_id AND r.map_id=m.id AND r.map_digest=m.map_digest
                WHERE m.tenant_id=%s AND m.workspace_id=%s AND m.organization_id=%s AND m.legal_entity_id=ANY(%s)
                ORDER BY m.legal_entity_id,m.id LIMIT 100""",
                (scope.tenant_id, scope.workspace_id, scope.organization_id, sorted(principal.authorized_legal_entity_ids))))}}

    return execute(request, user, collect)


@router.post("/sources")
def prepare(request: Request, payload: PreparationRequest, user: Prepare) -> dict[str, Any]:
    authority(request, "prepare")

    def invoke(repository: PostgresIntercompanyOperationsRepository, actor: PostingActor, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        identifiers = [payload.seller_entity_id, payload.buyer_entity_id, payload.adjustment_entity_id]
        entities = records(repository.connection.execute("SELECT id,entity_code FROM reconforge.legal_entities WHERE tenant_id=%s AND organization_id=%s AND id=ANY(%s)", (scope.tenant_id, scope.organization_id, identifiers)))
        codes = {row["id"]: row["entity_code"] for row in entities}
        if len(codes) != 3:
            raise APIError(status_code=403, code="intercompany_scope_denied", message="Three distinct authorized entity scopes are required.")
        args = payload.model_dump(exclude={"command_id", "amount_minor"})
        args.update(workspace_id=scope.workspace_id, organization_id=scope.organization_id, organization_code=scope.organization_code,
                    seller_entity_code=codes[payload.seller_entity_id], buyer_entity_code=codes[payload.buyer_entity_id],
                    adjustment_entity_code=codes[payload.adjustment_entity_id], amount_minor=int(payload.amount_minor))
        return {"plan": repository.prepare(IntercompanyPreparation(**args), command_id=payload.command_id, actor=actor)}

    return execute(request, user, invoke)


@router.get("/sources")
def sources(request: Request, user: Read, after: str = Query(default="", max_length=160)) -> dict[str, Any]:
    authority(request, "read")
    return execute(request, user, lambda repository, actor, scope: {"sources": repository.list_sources(
        workspace_id=scope.workspace_id, organization_id=str(scope.organization_id), after=after, actor=actor)})


@router.get("/sources/{source_id}")
def source(request: Request, source_id: str, user: Read) -> dict[str, Any]:
    authority(request, "read")
    return execute(request, user, lambda repository, actor, scope: {"source": repository.get_source(source_id, actor=actor)})


@router.post("/sources/{source_id}/settlements")
def settlement(request: Request, source_id: str, payload: SettlementRequest, user: Prepare) -> dict[str, Any]:
    authority(request, "prepare")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.prepare_settlement(source_id,
        amount_minor=int(payload.amount_minor), period_id=payload.period_id, posting_date=payload.posting_date,
        reason=payload.reason, command_id=payload.command_id, actor=actor)})


@router.post("/sources/{source_id}/eliminations")
def elimination(request: Request, source_id: str, payload: EliminationRequest, user: Prepare) -> dict[str, Any]:
    authority(request, "prepare")
    return execute(request, user, lambda repository, actor, scope: {"plan": repository.prepare_elimination(source_id,
        period_id=payload.period_id, posting_date=payload.posting_date, reason=payload.reason, command_id=payload.command_id, actor=actor)})


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
def report(request: Request, source_id: str, user: Read, seller_map_id: str = Query(min_length=1, max_length=160),
           buyer_map_id: str = Query(min_length=1, max_length=160), adjustment_map_id: str = Query(min_length=1, max_length=160),
           period_id: str = Query(min_length=1, max_length=160), as_of_date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict[str, Any]:
    authority(request, "read")
    return execute(request, user, lambda repository, actor, scope: {"report": repository.report(source_id,
        seller_map_id=seller_map_id, buyer_map_id=buyer_map_id, adjustment_map_id=adjustment_map_id,
        period_id=period_id, as_of_date=as_of_date, actor=actor)})
