"""Read-only original Project cost/revenue and whole-source cash evidence."""

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import StreamingResponse

from reconforge.api.errors import APIError
from reconforge.api.routes.finance_posting import _actor
from reconforge.api.routes.people_project_payroll import people_scope
from reconforge.api.routes.procurement_operations import required
from reconforge.api.server_finance_core import (
    FinanceCoreExecutionScope,
    execute_postgres_finance_core_scoped,
    server_finance_core_enabled,
)
from reconforge.application.accrual_deferral_evidence import evidence_chunks, evidence_size
from reconforge.application.project_source_reconciliation import ProjectSourceReconciliationService
from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.project_source_reconciliation import ProjectSourceSelection
from reconforge.infrastructure.postgres_project_source_reconciliation import (
    PostgresProjectSourceReconciliationRepository,
)

router = APIRouter(prefix="/project-source-reconciliation", tags=["project-source-reconciliation"])
READ_PERMISSIONS = frozenset(
    {"people_project_payroll.read", "project_time_billing.read", "finance_core.read", "receivables.read"}
)
Read = Annotated[LocalUser, Depends(required(READ_PERMISSIONS))]
Identifier = Annotated[str, Query(min_length=1, max_length=160)]


def capture(
    request: Request, user: LocalUser, project_id: str, period_id: str, payrun_id: str, invoice_id: str
) -> dict[str, Any]:
    if not server_finance_core_enabled(request):
        raise APIError(
            status_code=503,
            code="project_reconciliation_backend_unavailable",
            message="Original governed Project sources require PostgreSQL.",
        )
    actor = _actor(request, user)

    def invoke(finance: Any, scope: FinanceCoreExecutionScope) -> dict[str, Any]:
        try:
            selection = ProjectSourceSelection(people_scope(scope), project_id, period_id, payrun_id, invoice_id)
            return ProjectSourceReconciliationService(
                PostgresProjectSourceReconciliationRepository(finance.connection, scope.tenant_id)
            ).report(selection, actor=actor)
        except FinancePostingError as exc:
            status = (
                403
                if "denied" in exc.code
                else 404
                if "not_found" in exc.code
                else 503
                if "unavailable" in exc.code
                else 409
            )
            raise APIError(status_code=status, code=exc.code, message=str(exc)) from exc

    return execute_postgres_finance_core_scoped(request, invoke)


@router.get("/report")
def report(
    request: Request,
    user: Read,
    project_id: Identifier,
    period_id: Identifier,
    payrun_id: Identifier,
    invoice_id: Identifier,
) -> dict[str, Any]:
    # Summary amounts are canonical strings; raw integer evidence is streamed
    # separately so a JSON client cannot silently round native 64-bit money.
    return {"report": capture(request, user, project_id, period_id, payrun_id, invoice_id)["report"]}


@router.get("/evidence")
def evidence(
    request: Request,
    user: Read,
    project_id: Identifier,
    period_id: Identifier,
    payrun_id: Identifier,
    invoice_id: Identifier,
) -> StreamingResponse:
    retained = capture(request, user, project_id, period_id, payrun_id, invoice_id)
    length = evidence_size(retained)
    raw_digest = hashlib.sha256()
    for chunk in evidence_chunks(retained):
        raw_digest.update(chunk)
    return StreamingResponse(
        evidence_chunks(retained),
        media_type="application/json",
        headers={
            "Content-Length": str(length),
            "Content-Disposition": 'attachment; filename="project-source-evidence.json"',
            "X-ReconForge-Evidence-Digest": retained["evidence_digest"],
            "X-ReconForge-Report-Digest": retained["report"]["report_digest"],
            "X-ReconForge-Raw-SHA256": raw_digest.hexdigest(),
        },
    )
