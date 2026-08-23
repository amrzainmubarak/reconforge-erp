"""Authenticated PostgreSQL API for non-posting consolidation impairment evidence."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import enforce_server_scoped_permissions, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_consolidation_impairment import (
    execute_postgres_impairment,
    server_impairment_enabled,
)
from reconforge.application.consolidation_impairment import ConsolidationImpairmentApplicationService
from reconforge.auth.models import LocalUser
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_impairment import (
    ConsolidationImpairmentBridgeRequest,
    ConsolidationImpairmentUnit,
)
from reconforge.utils.money import Money

router = APIRouter(prefix="/consolidation-impairment", tags=["consolidation-impairment"])
ImpairmentRead = Annotated[LocalUser, Depends(require_any_permission({"finance_core.read", "finance_core.manage"}))]
ImpairmentPrepare = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]


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


class ImpairmentUnitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    unit_id: str = Field(min_length=1, max_length=160)
    unit_kind: Literal["goodwill", "asset"]
    account_code: str = Field(min_length=1, max_length=160)
    carrying_amount: CanonicalMoneyRequest
    recoverable_amount: CanonicalMoneyRequest
    source_reference: str = Field(min_length=1, max_length=160)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ImpairmentPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    impairment_test_id: str = Field(min_length=1, max_length=160)
    entity_code: str = Field(min_length=1, max_length=160)
    period_id: str = Field(min_length=1, max_length=160)
    reporting_currency: str = Field(min_length=1, max_length=8)
    units: list[ImpairmentUnitRequest] = Field(min_length=1, max_length=4096)
    policy_id: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=32)
    source_reference: str = Field(min_length=1, max_length=160)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_by: str = Field(min_length=1, max_length=160)
    prepared_at: str = Field(min_length=1, max_length=64)
    approved_at: str = Field(min_length=1, max_length=64)

    @staticmethod
    def _money(value: CanonicalMoneyRequest) -> Money:
        try:
            return Money.from_canonical_dict(value.model_dump(mode="python"))
        except (TypeError, ValueError, KeyError) as exc:
            raise APIError(
                status_code=400,
                code="consolidation_impairment_request_invalid",
                message="Impairment monetary input is not a valid canonical Money value.",
            ) from exc

    def to_domain(self, *, prepared_by: str) -> ConsolidationImpairmentBridgeRequest:
        try:
            return ConsolidationImpairmentBridgeRequest(
                impairment_test_id=self.impairment_test_id,
                entity_code=self.entity_code,
                period_id=self.period_id,
                reporting_currency=self.reporting_currency,
                units=tuple(
                    ConsolidationImpairmentUnit(
                        unit_id=unit.unit_id,
                        unit_kind=unit.unit_kind,
                        account_code=unit.account_code,
                        carrying_amount=self._money(unit.carrying_amount),
                        recoverable_amount=self._money(unit.recoverable_amount),
                        source_reference=unit.source_reference,
                        source_digest=unit.source_digest,
                    )
                    for unit in self.units
                ),
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                source_reference=self.source_reference,
                source_digest=self.source_digest,
                prepared_by=prepared_by,
                prepared_at=self.prepared_at,
                approved_by=self.approved_by,
                approved_at=self.approved_at,
            )
        except APIError:
            raise
        except (ConsolidationError, TypeError, ValueError) as exc:
            raise APIError(
                status_code=400,
                code="consolidation_impairment_request_invalid",
                message="Impairment request failed deterministic validation.",
            ) from exc


def _server_only(request: Request) -> None:
    if not server_impairment_enabled(request):
        raise APIError(
            status_code=503,
            code="consolidation_impairment_unavailable",
            message="Consolidation impairment persistence requires the PostgreSQL server profile.",
        )


def _enforce_server_policy(
    request: Request,
    *,
    permissions: frozenset[str],
    amount: Decimal | None = None,
) -> None:
    """Re-evaluate tenant policy before accessing tenant-scoped evidence."""

    from reconforge.api.server_identity import request_tenant_id

    enforce_server_scoped_permissions(
        request,
        permissions=permissions,
        tenant_id=request_tenant_id(request),
        workspace_id=None,
        amount=amount,
    )


@router.post("")
def prepare_impairment(
    request: Request,
    payload: ImpairmentPrepareRequest,
    current_user: ImpairmentPrepare,
) -> dict[str, object]:
    """Persist one authenticated, maker-checker, non-posting impairment artifact."""

    _server_only(request)
    domain_request = payload.to_domain(prepared_by=current_user.id)
    total_carrying_amount = sum(
        (unit.carrying_amount.amount for unit in domain_request.units),
        Decimal("0"),
    )
    _enforce_server_policy(
        request,
        permissions=frozenset({"finance_core.manage"}),
        amount=total_carrying_amount,
    )
    artifact = execute_postgres_impairment(
        request,
        lambda repository, _tenant: ConsolidationImpairmentApplicationService(repository).prepare_and_persist(
            domain_request,
            actor_label=current_user.id,
        ),
    )
    return {
        "artifact": artifact,
        "source": {"kind": "postgresql-consolidation-impairment", "server_mode": True},
    }


@router.get("/{artifact_id}")
def get_impairment(
    artifact_id: str,
    request: Request,
    current_user: ImpairmentRead,
) -> dict[str, object]:
    """Return one tenant-scoped, replay-verified impairment artifact."""

    _server_only(request)
    _enforce_server_policy(request, permissions=frozenset({"finance_core.read", "finance_core.manage"}))
    artifact = execute_postgres_impairment(
        request,
        lambda repository, _tenant: repository.get(artifact_id, actor_label=current_user.id),
    )
    return {
        "artifact": artifact,
        "source": {"kind": "postgresql-consolidation-impairment", "server_mode": True},
    }


__all__ = [
    "CanonicalMoneyRequest",
    "ImpairmentPrepareRequest",
    "ImpairmentUnitRequest",
    "get_impairment",
    "prepare_impairment",
    "router",
]
