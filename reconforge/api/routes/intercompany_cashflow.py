"""Explicit-opening read views over the already governed native IC2 source."""

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.fixed_assets import project
from reconforge.api.routes.intercompany_fx import Read, authority
from reconforge.api.server_finance_core import execute_postgres_finance_core_scoped, server_finance_core_enabled
from reconforge.application.accrual_deferral_evidence import evidence_chunks, evidence_digest, evidence_size
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.intercompany_cashflow import SourceCashOpening
from reconforge.infrastructure.postgres_intercompany_cashflow import PostgresIntercompanyCashflowRepository

router = APIRouter(prefix="/intercompany-source-cashflow", tags=["intercompany-source-cashflow"])


class OpeningQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin_plan_id: str = Field(min_length=1, max_length=160)
    origin_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    seller_opening_minor: str = Field(pattern=r"^(?:0|-?[1-9][0-9]{0,18})$")
    buyer_opening_minor: str = Field(pattern=r"^(?:0|-?[1-9][0-9]{0,18})$")
    opening_basis: str = Field(min_length=1, max_length=160)

    def retained(self, source_id: str) -> SourceCashOpening:
        return SourceCashOpening(source_id, self.source_digest, self.origin_plan_id, self.origin_plan_digest,
            int(self.seller_opening_minor), int(self.buyer_opening_minor), self.opening_basis)


def capture(source_id: str, request: Request, user: Read, opening: OpeningQuery) -> dict[str, Any]:
    authority(request, "read")
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="intercompany_cashflow_backend_unavailable",
            message="Original native IC2 source cashflow requires PostgreSQL.")
    actor = _actor(request, user)

    def invoke(finance: Any, scope: Any) -> dict[str, Any]:
        try:
            return PostgresIntercompanyCashflowRepository(finance.connection, scope.tenant_id).evidence(
                source_id, opening=opening.retained(source_id), actor=actor)
        except FinancePostingError as exc:
            status = 403 if "denied" in exc.code else 404 if "not_found" in exc.code else 413 if "too_large" in exc.code else 400
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.get("/sources/{source_id}")
def view(source_id: str, request: Request, user: Read, opening: Annotated[OpeningQuery, Query()]) -> dict[str, Any]:
    retained = capture(source_id, request, user, opening)
    return {"cashflow": project(retained["cashflow"]), "evidence_digest": retained["evidence_digest"],
        "qualified_scope": retained["qualified_scope"], "evidence_sha256": evidence_digest(retained),
        "evidence_bytes": evidence_size(retained)}


@router.get("/sources/{source_id}/evidence/export")
def export(source_id: str, request: Request, user: Read, opening: Annotated[OpeningQuery, Query()]) -> StreamingResponse:
    retained = capture(source_id, request, user, opening)
    try:
        length, sha = evidence_size(retained), evidence_digest(retained)
    except FinancePostingError as exc:
        raise APIError(status_code=413 if "too_large" in exc.code else 400, code=exc.code, message=str(exc)) from exc
    # Complete authorization and immutable native capture occur before headers;
    # the generator never retains a database connection or performs lazy reads.
    return StreamingResponse(evidence_chunks(retained), media_type="application/json",
        headers={"Content-Length": str(length), "Content-Disposition": 'attachment; filename="intercompany-source-cashflow-evidence.json"',
            "X-ReconForge-Evidence-SHA256": sha})
