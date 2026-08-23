"""Authenticated PostgreSQL API for non-posting intercompany elimination evidence."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import enforce_server_scoped_permission, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_consolidation_intercompany import (
    execute_postgres_consolidation_intercompany,
    server_consolidation_intercompany_enabled,
)
from reconforge.api.server_identity import RequestExecutionScope, request_execution_scope
from reconforge.application.intercompany_elimination import IntercompanyEliminationApplicationService
from reconforge.auth.models import LocalUser
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.intercompany_elimination import IntercompanyEliminationInputLine
from reconforge.utils.money import Money

router = APIRouter(prefix="/consolidation-intercompany-eliminations", tags=["consolidation-intercompany"])
IntercompanyRead = Annotated[LocalUser, Depends(require_any_permission({"finance_core.read", "finance_core.manage"}))]
IntercompanyManage = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]


class CanonicalMoneyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    amount: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=1, max_length=8)
    currency_policy_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    currency_registry_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    currency_registry_version: str = Field(min_length=1, max_length=128)
    minor_units: int = Field(ge=0, le=8)
    rounding_policy: Literal["ROUND_HALF_UP"]
    schema_version: int = Field(ge=1, le=1)


class IntercompanyLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    transaction_id: str = Field(min_length=1, max_length=160)
    period_name: str = Field(min_length=1, max_length=160)
    entity_code: str = Field(min_length=1, max_length=160)
    counterparty_code: str = Field(min_length=1, max_length=160)
    reference: str = Field(min_length=1, max_length=160)
    group_account_code: str = Field(min_length=1, max_length=160)
    account_type: Literal["Asset", "Liability", "Equity", "Income", "Expense"]
    amount: CanonicalMoneyRequest
    source_reference: str = Field(min_length=1, max_length=500)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    def to_domain(self) -> IntercompanyEliminationInputLine:
        try:
            return IntercompanyEliminationInputLine(
                transaction_id=self.transaction_id,
                period_name=self.period_name,
                entity_code=self.entity_code,
                counterparty_code=self.counterparty_code,
                reference=self.reference,
                group_account_code=self.group_account_code,
                account_type=self.account_type,
                amount=Money.from_canonical_dict(self.amount.model_dump(mode="python")),
                source_reference=self.source_reference,
                source_digest=self.source_digest,
            )
        except (ConsolidationError, TypeError, ValueError, KeyError) as exc:
            raise APIError(
                status_code=400,
                code="consolidation_intercompany_request_invalid",
                message="Intercompany source line failed deterministic validation.",
            ) from exc


class IntercompanyPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    workspace: str = Field(min_length=1, max_length=160)
    reporting_currency: str = Field(min_length=1, max_length=8)
    version: str = Field(pattern=r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
    prepared_at: str = Field(min_length=1, max_length=64)
    lines: list[IntercompanyLineRequest] = Field(min_length=1, max_length=100_000)


def _server_only(request: Request) -> None:
    if not server_consolidation_intercompany_enabled(request):
        raise APIError(
            status_code=503,
            code="consolidation_intercompany_unavailable",
            message="Intercompany elimination persistence requires the PostgreSQL server profile.",
        )


def _scope_for_payload(
    request: Request,
    workspace: str,
    *,
    amount: Decimal | None = None,
) -> RequestExecutionScope:
    scope = request_execution_scope(request)
    if workspace.strip() != scope.workspace_id:
        raise APIError(status_code=403, code="workspace_scope_denied", message="Workspace scope is not authorized.")
    enforce_server_scoped_permission(
        request,
        permission="finance_core.manage",
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        organization_id=scope.organization_id,
        entity_id=scope.legal_entity_id,
        amount=amount,
    )
    return scope


@router.post("")
def prepare_intercompany(
    request: Request,
    payload: IntercompanyPrepareRequest,
    current_user: IntercompanyManage,
) -> dict[str, object]:
    """Compute and persist one replay-verified, non-posting artifact."""

    _server_only(request)
    lines = tuple(line.to_domain() for line in payload.lines)
    gross_amount = sum((abs(line.amount.amount) for line in lines), Decimal("0"))
    scope = _scope_for_payload(request, payload.workspace, amount=gross_amount)
    artifact = execute_postgres_consolidation_intercompany(
        request,
        lambda repository, _tenant: IntercompanyEliminationApplicationService(repository).prepare_and_persist(
            lines,
            reporting_currency=payload.reporting_currency,
            prepared_by=current_user.id,
            prepared_at=payload.prepared_at,
            version=payload.version,
            workspace=scope.workspace_id,
            actor_label=current_user.id,
        ),
    )
    return {
        "artifact": artifact,
        "source": {"kind": "postgresql-consolidation-intercompany", "server_mode": True},
    }


@router.get("/{artifact_id}")
def get_intercompany(
    artifact_id: str,
    request: Request,
    current_user: IntercompanyRead,
) -> dict[str, object]:
    """Return one tenant/workspace-scoped artifact after replay verification."""

    _server_only(request)
    scope = request_execution_scope(request)
    enforce_server_scoped_permission(
        request,
        permission="finance_core.read",
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        organization_id=scope.organization_id,
        entity_id=scope.legal_entity_id,
    )
    artifact = execute_postgres_consolidation_intercompany(
        request,
        lambda repository, _tenant: repository.get(artifact_id, actor_label=current_user.id),
    )
    if artifact.get("workspace_id") != scope.workspace_id:
        raise APIError(status_code=404, code="consolidation_intercompany_not_found", message="Artifact was not found.")
    return {
        "artifact": artifact,
        "source": {"kind": "postgresql-consolidation-intercompany", "server_mode": True},
    }


__all__ = [
    "CanonicalMoneyRequest",
    "IntercompanyLineRequest",
    "IntercompanyPrepareRequest",
    "get_intercompany",
    "prepare_intercompany",
    "router",
]
