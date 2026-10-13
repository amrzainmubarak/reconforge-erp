"""Exact selected source pins govern a read-only native group diagnostic."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.fixed_assets import project
from reconforge.api.routes.intercompany_fx import Read, authority
from reconforge.api.server_finance_core import execute_postgres_finance_core_scoped, server_finance_core_enabled
from reconforge.application.accrual_deferral_evidence import evidence_digest, evidence_size, evidence_transport_chunks
from reconforge.application.intercompany_group_diagnostic import IntercompanyGroupDiagnosticService
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.intercompany_cashflow import SourceCashOpening
from reconforge.domain.intercompany_group_diagnostic import IntercompanyDiagnosticSelection, IntercompanyReportPin
from reconforge.infrastructure.postgres_intercompany_group_diagnostic import (
    PostgresIntercompanyGroupDiagnosticRepository,
)

router = APIRouter(prefix="/intercompany-group-diagnostic", tags=["intercompany-group-diagnostic"])
SelectionQuery = Annotated[str, Query(min_length=1, max_length=32_768)]
Digest = Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=160)]


class OpeningInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: str = Field(pattern="^IC2S-[0-9a-f]{32}$")
    source_digest: Digest
    origin_plan_id: Identifier
    origin_plan_digest: Digest
    seller_minor: int
    buyer_minor: int
    basis: Identifier


class PinInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    opening: OpeningInput
    elimination_plan_id: Identifier
    elimination_plan_digest: Digest
    report_digest: Digest


class SelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pins: list[PinInput] = Field(min_length=1, max_length=16)


def parse_selection(raw: str) -> IntercompanyDiagnosticSelection:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        if len({key for key, _ in items}) != len(items):
            raise ValueError("Duplicate selected source fields are ambiguous.")
        return dict(items)
    try:
        if not 1 <= len(raw) <= 32_768:
            raise ValueError("Selected source query exceeds its explicit bound.")
        value = SelectionInput.model_validate(json.loads(raw, object_pairs_hook=pairs))
        return IntercompanyDiagnosticSelection(tuple(IntercompanyReportPin(SourceCashOpening(**pin.opening.model_dump()),
            pin.elimination_plan_id, pin.elimination_plan_digest, pin.report_digest) for pin in value.pins))
    except (ValueError, ValidationError, FinancePostingError) as exc:
        raise APIError(status_code=400, code="intercompany_group_selection_invalid",
                       message="Select one to sixteen unique canonically ordered original source/report pins.") from exc


def capture(request: Request, user: Read, raw_selection: str) -> dict[str, Any]:
    authority(request, "read")
    selection = parse_selection(raw_selection)
    if not server_finance_core_enabled(request):
        raise APIError(status_code=503, code="intercompany_group_backend_unavailable",
                       message="Original native selected-group diagnostics require PostgreSQL.")
    actor = _actor(request, user)
    def invoke(finance: Any, scope: Any) -> dict[str, Any]:
        try:
            return IntercompanyGroupDiagnosticService(
                PostgresIntercompanyGroupDiagnosticRepository(finance.connection, scope.tenant_id)
            ).evidence(selection, actor=actor)
        except FinancePostingError as exc:
            status = 403 if "denied" in exc.code else 404 if "not_found" in exc.code else 413 if "too_large" in exc.code else 400
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc
    return execute_postgres_finance_core_scoped(request, invoke)


@router.get("/report")
def report(request: Request, user: Read, selection: SelectionQuery) -> dict[str, Any]:
    retained = capture(request, user, selection)
    return {"diagnostic": project(retained["diagnostic"]), "evidence_digest": retained["evidence_digest"],
        "evidence_sha256": evidence_digest(retained), "evidence_bytes": evidence_size(retained)}


@router.get("/evidence")
def evidence(request: Request, user: Read, selection: SelectionQuery) -> StreamingResponse:
    retained = capture(request, user, selection)
    length, sha = evidence_size(retained), evidence_digest(retained)
    return StreamingResponse(evidence_transport_chunks(retained), media_type="application/json",
        headers={"Content-Length": str(length), "X-ReconForge-Evidence-SHA256": sha,
                 "Content-Disposition": 'attachment; filename="intercompany-group-diagnostic-original.json"'})
