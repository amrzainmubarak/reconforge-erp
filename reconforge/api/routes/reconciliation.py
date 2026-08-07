"""Tenant-scoped submission, control, and read APIs for PostgreSQL reconciliation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import enforce_server_scoped_permissions, require_any_permission
from reconforge.api.errors import APIError
from reconforge.api.server_identity import request_execution_scope
from reconforge.api.server_reconciliation import execute_postgres_reconciliation, server_reconciliation_enabled
from reconforge.auth.models import LocalUser
from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY, InvalidAmountError, parse_exact_amount

router = APIRouter(prefix="/reconciliations", tags=["reconciliations"])
MAX_LIMIT = 1_000
MAX_OFFSET = 10_000_000
MAX_SUBMISSION_BYTES = 20_000_000

ReconciliationRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"reconciliation.read", "reconciliation.manage", "match.read", "match.run"})),
]
ReconciliationManage = Annotated[
    LocalUser,
    Depends(require_any_permission({"reconciliation.manage", "match.run"})),
]
PageLimit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=MAX_OFFSET)]


class ExecutionReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=500)


class CanonicalInputRequest(BaseModel):
    """One strict, source-lineage-preserving reconciliation input."""

    model_config = ConfigDict(extra="forbid")

    side: str = Field(min_length=1, max_length=16)
    source_id: str = Field(min_length=1, max_length=255)
    record_hash: str = Field(min_length=1, max_length=128)
    amount: str | None = Field(default=None, max_length=64)
    amount_original: str = Field(default="", max_length=255)
    currency_code: str = Field(default="", max_length=3)
    date_original: str = Field(default="", max_length=64)
    date_value: str | None = Field(default=None, max_length=10)
    reference_original: str = Field(default="", max_length=512)
    reference_normalized: str = Field(default="", max_length=512)
    attributes: dict[str, Any] = Field(default_factory=dict)
    valid: bool = True
    allowed_uses: int = Field(default=1, ge=1, le=1_000)


class ReconciliationRunSubmissionRequest(BaseModel):
    """Bounded run manifest and canonical inputs submitted atomically."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=255)
    left_source: str = Field(min_length=1, max_length=512)
    right_source: str = Field(min_length=1, max_length=512)
    algorithm_version: str = Field(default="deterministic-global-v1", min_length=1, max_length=64)
    rule: dict[str, Any] = Field(default_factory=dict)
    input_hash: str = Field(min_length=1, max_length=128)
    inputs: list[CanonicalInputRequest] = Field(min_length=1, max_length=5_000)
    reason: str = Field(default="", max_length=500)


def _server_only(request: Request) -> None:
    if not server_reconciliation_enabled(request):
        raise APIError(
            status_code=501,
            code="reconciliation_server_only",
            message="Persisted reconciliation result reads are available only in PostgreSQL server mode.",
        )


def _enforce_server_run_scope(request: Request) -> None:
    scope = request_execution_scope(request)
    enforce_server_scoped_permissions(
        request,
        permissions=frozenset({"reconciliation.manage", "match.run"}),
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        organization_id=scope.organization_id,
        entity_id=scope.legal_entity_id,
    )


def _enforce_server_read_scope(request: Request) -> None:
    scope = request_execution_scope(request)
    enforce_server_scoped_permissions(
        request,
        permissions=frozenset({"reconciliation.read", "reconciliation.manage", "match.read", "match.run"}),
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        organization_id=scope.organization_id,
        entity_id=scope.legal_entity_id,
    )


def _source() -> dict[str, object]:
    return {"kind": "postgresql-reconciliation-results", "server_mode": True}


@router.post("/runs", status_code=202)
def submit_run(
    request: Request,
    payload: ReconciliationRunSubmissionRequest,
    current_user: ReconciliationManage,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=160)] = None,
) -> dict[str, object]:
    """Create a queued run and register its canonical inputs atomically."""

    _server_only(request)
    _enforce_server_run_scope(request)
    if len(payload.model_dump_json().encode("utf-8")) > MAX_SUBMISSION_BYTES:
        raise APIError(
            status_code=413,
            code="reconciliation_request_too_large",
            message="The reconciliation submission exceeds the bounded request size.",
        )
    sides = {item.side.casefold() for item in payload.inputs}
    if sides != {"left", "right"}:
        raise APIError(
            status_code=400,
            code="reconciliation_request_invalid",
            message="inputs must contain at least one Left and one Right record.",
        )
    rule = dict(payload.rule)
    requested_input_policy = rule.get("financial_input_policy", STRICT_FINANCIAL_INPUT_POLICY)
    if requested_input_policy != STRICT_FINANCIAL_INPUT_POLICY:
        raise APIError(
            status_code=400,
            code="reconciliation_financial_input_policy_invalid",
            message="New reconciliation runs require the current strict financial input policy.",
        )
    rule["financial_input_policy"] = STRICT_FINANCIAL_INPUT_POLICY
    requested_identity_policy = rule.get("record_identity_policy", RECORD_IDENTITY_POLICY)
    if requested_identity_policy != RECORD_IDENTITY_POLICY:
        raise APIError(
            status_code=400,
            code="reconciliation_record_identity_policy_invalid",
            message="New reconciliation runs require the current record identity policy.",
        )
    rule["record_identity_policy"] = RECORD_IDENTITY_POLICY
    try:
        amount_tolerance = parse_exact_amount(rule.get("amount_tolerance", "0"))
    except InvalidAmountError as exc:
        raise APIError(
            status_code=400,
            code="reconciliation_rule_invalid",
            message="amount_tolerance must be a non-negative exact decimal value.",
        ) from exc
    if amount_tolerance < 0:
        raise APIError(
            status_code=400,
            code="reconciliation_rule_invalid",
            message="amount_tolerance must be a non-negative exact decimal value.",
        )
    rule["amount_tolerance"] = format(amount_tolerance, "f")

    def submit(repository: Any, tenant: str) -> dict[str, object]:
        run = repository.create_run(
            tenant_id=tenant,
            run_id=payload.run_id,
            name=payload.name,
            left_source=payload.left_source,
            right_source=payload.right_source,
            algorithm_version=payload.algorithm_version,
            rule=rule,
            input_hash=payload.input_hash,
            actor_id=current_user.id,
            idempotency_key=idempotency_key,
            request_id=str(getattr(request.state, "request_id", "")),
            reason=payload.reason,
        )
        for item in payload.inputs:
            repository.register_input(
                tenant_id=tenant,
                run_id=payload.run_id,
                side=item.side,
                source_id=item.source_id,
                record_hash=item.record_hash,
                amount=item.amount,
                amount_original=item.amount_original,
                currency_code=item.currency_code,
                date_original=item.date_original,
                date_value=item.date_value,
                reference_original=item.reference_original,
                reference_normalized=item.reference_normalized,
                attributes=item.attributes,
                valid=item.valid,
                allowed_uses=item.allowed_uses,
            )
        return {"run": run, "input_count": len(payload.inputs)}

    submitted = execute_postgres_reconciliation(request, submit)
    return {**submitted, "source": _source()}


@router.get("/runs")
def list_runs(
    request: Request,
    current_user: ReconciliationRead,
    status: str = "all",
    execution_status: str = "",
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List tenant-scoped reconciliation run metadata."""

    _server_only(request)
    _enforce_server_read_scope(request)
    runs = execute_postgres_reconciliation(
        request,
        lambda repository, tenant: repository.list_runs(
            tenant_id=tenant,
            status="" if status.casefold() == "all" else status,
            execution_status=execution_status,
            limit=limit,
            offset=offset,
        ),
    )
    return {"runs": runs, "pagination": {"limit": limit, "offset": offset, "returned": len(runs)}, "source": _source()}


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    request: Request,
    current_user: ReconciliationRead,
) -> dict[str, object]:
    """Return persisted run metadata; child collections have paginated endpoints."""

    _server_only(request)
    _enforce_server_read_scope(request)
    run = execute_postgres_reconciliation(
        request,
        lambda repository, tenant: repository.get_run_metadata(tenant_id=tenant, run_id=run_id),
    )
    return {"run": run, "source": _source()}


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    request: Request,
    payload: ExecutionReasonRequest,
    current_user: ReconciliationManage,
) -> dict[str, object]:
    """Request cooperative cancellation of a running reconciliation."""

    _server_only(request)
    _enforce_server_run_scope(request)
    run = execute_postgres_reconciliation(
        request,
        lambda repository, tenant: repository.cancel_run(
            tenant_id=tenant,
            run_id=run_id,
            actor_id=current_user.id,
            request_id=str(getattr(request.state, "request_id", "")),
            reason=payload.reason,
        ),
    )
    return {"run": run, "source": _source()}


@router.post("/runs/{run_id}/requeue")
def requeue_run(
    run_id: str,
    request: Request,
    payload: ExecutionReasonRequest,
    current_user: ReconciliationManage,
) -> dict[str, object]:
    """Explicitly requeue a failed or cancelled reconciliation."""

    _server_only(request)
    _enforce_server_run_scope(request)
    run = execute_postgres_reconciliation(
        request,
        lambda repository, tenant: repository.requeue_run(
            tenant_id=tenant,
            run_id=run_id,
            actor_id=current_user.id,
            request_id=str(getattr(request.state, "request_id", "")),
            reason=payload.reason,
        ),
    )
    return {"run": run, "source": _source()}


def _list_children(
    request: Request,
    run_id: str,
    operation: Callable[..., list[dict[str, object]]],
    *,
    limit: int,
    offset: int,
) -> dict[str, object]:
    _server_only(request)
    _enforce_server_read_scope(request)
    records = execute_postgres_reconciliation(
        request,
        lambda repository, tenant: operation(
            repository,
            tenant_id=tenant,
            run_id=run_id,
            limit=limit,
            offset=offset,
        ),
    )
    return {
        "records": records,
        "pagination": {"limit": limit, "offset": offset, "returned": len(records)},
        "source": _source(),
    }


@router.get("/runs/{run_id}/inputs")
def list_inputs(
    run_id: str,
    request: Request,
    current_user: ReconciliationRead,
    limit: PageLimit = 500,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List canonical source inputs for a persisted run."""

    result = _list_children(
        request, run_id, lambda repository, **values: repository.list_inputs(**values), limit=limit, offset=offset
    )
    result["inputs"] = result.pop("records")
    return result


@router.get("/runs/{run_id}/results")
def list_results(
    run_id: str,
    request: Request,
    current_user: ReconciliationRead,
    limit: PageLimit = 500,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List explainable deterministic results for a persisted run."""

    result = _list_children(
        request, run_id, lambda repository, **values: repository.list_results(**values), limit=limit, offset=offset
    )
    result["results"] = result.pop("records")
    return result


@router.get("/runs/{run_id}/exceptions")
def list_exceptions(
    run_id: str,
    request: Request,
    current_user: ReconciliationRead,
    limit: PageLimit = 500,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List typed, risk-scored exceptions for a persisted run."""

    result = _list_children(
        request, run_id, lambda repository, **values: repository.list_exceptions(**values), limit=limit, offset=offset
    )
    result["exceptions"] = result.pop("records")
    return result
