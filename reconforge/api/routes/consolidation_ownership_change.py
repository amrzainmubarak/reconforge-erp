"""Authenticated PostgreSQL API for non-posting ownership-change evidence."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import enforce_server_scoped_permissions, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_consolidation_ownership_change import (
    execute_postgres_ownership_change,
    server_ownership_change_enabled,
)
from reconforge.application.consolidation_ownership_change import OwnershipChangeApplicationService
from reconforge.auth.models import LocalUser
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_ownership_changes import OwnershipChangeAdjustmentRequest
from reconforge.utils.money import Money

router = APIRouter(prefix="/consolidation-ownership-change", tags=["consolidation-ownership-change"])
OwnershipChangeRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"finance_core.read", "finance_core.manage"})),
]
OwnershipChangePrepare = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]


class OwnershipChangeMoneyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    amount: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=1, max_length=8)
    currency_policy_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    currency_registry_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    currency_registry_version: str = Field(min_length=1, max_length=128)
    minor_units: int = Field(ge=0, le=8)
    rounding_policy: Literal["ROUND_HALF_UP"]
    schema_version: int = Field(ge=1, le=1)


class OwnershipChangePrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    change_id: str = Field(min_length=1, max_length=160)
    subsidiary_entity_code: str = Field(min_length=1, max_length=160)
    period_id: str = Field(min_length=1, max_length=160)
    effective_date: str = Field(min_length=1, max_length=32)
    reporting_currency: str = Field(min_length=1, max_length=8)
    prior_group_ownership_percentage: str = Field(min_length=1, max_length=128)
    new_group_ownership_percentage: str = Field(min_length=1, max_length=128)
    net_assets: OwnershipChangeMoneyRequest
    consideration_effect: OwnershipChangeMoneyRequest
    nci_account_code: str = Field(min_length=1, max_length=160)
    consideration_account_code: str = Field(min_length=1, max_length=160)
    parent_equity_account_code: str = Field(min_length=1, max_length=160)
    policy_id: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=32)
    source_reference: str = Field(min_length=1, max_length=160)
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_by: str = Field(min_length=1, max_length=160)
    prepared_at: str = Field(min_length=1, max_length=64)
    approved_at: str = Field(min_length=1, max_length=64)

    @staticmethod
    def _money(value: OwnershipChangeMoneyRequest) -> Money:
        try:
            return Money.from_canonical_dict(value.model_dump(mode="python"))
        except (TypeError, ValueError, KeyError) as exc:
            raise APIError(
                status_code=400,
                code="consolidation_ownership_change_request_invalid",
                message="Ownership-change monetary input is not a valid canonical Money value.",
            ) from exc

    @staticmethod
    def _percentage(value: str, field: str) -> Decimal:
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise APIError(
                status_code=400,
                code="consolidation_ownership_change_request_invalid",
                message=f"{field} must be a finite Decimal.",
            ) from exc
        if not parsed.is_finite():
            raise APIError(
                status_code=400,
                code="consolidation_ownership_change_request_invalid",
                message=f"{field} must be a finite Decimal.",
            )
        return parsed

    def to_domain(self, *, prepared_by: str) -> OwnershipChangeAdjustmentRequest:
        try:
            return OwnershipChangeAdjustmentRequest(
                change_id=self.change_id,
                subsidiary_entity_code=self.subsidiary_entity_code,
                period_id=self.period_id,
                effective_date=self.effective_date,
                reporting_currency=self.reporting_currency,
                prior_group_ownership_percentage=self._percentage(
                    self.prior_group_ownership_percentage, "Prior group ownership percentage"
                ),
                new_group_ownership_percentage=self._percentage(
                    self.new_group_ownership_percentage, "New group ownership percentage"
                ),
                net_assets=self._money(self.net_assets),
                consideration_effect=self._money(self.consideration_effect),
                nci_account_code=self.nci_account_code,
                consideration_account_code=self.consideration_account_code,
                parent_equity_account_code=self.parent_equity_account_code,
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
        except (ConsolidationError, TypeError, ValueError, InvalidOperation) as exc:
            raise APIError(
                status_code=400,
                code="consolidation_ownership_change_request_invalid",
                message="Ownership-change request failed deterministic validation.",
            ) from exc


def _server_only(request: Request) -> None:
    if not server_ownership_change_enabled(request):
        raise APIError(
            status_code=503,
            code="consolidation_ownership_change_unavailable",
            message="Consolidation ownership-change persistence requires the PostgreSQL server profile.",
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
def prepare_ownership_change(
    request: Request,
    payload: OwnershipChangePrepareRequest,
    current_user: OwnershipChangePrepare,
) -> dict[str, object]:
    """Persist one authenticated, maker-checker, non-posting ownership-change artifact."""

    _server_only(request)
    domain_request = payload.to_domain(prepared_by=current_user.id)
    ownership_delta_effect = domain_request.net_assets.amount * (
        domain_request.prior_group_ownership_percentage - domain_request.new_group_ownership_percentage
    )
    gross_exposure = abs(ownership_delta_effect) + abs(domain_request.consideration_effect.amount)
    _enforce_server_policy(
        request,
        permissions=frozenset({"finance_core.manage"}),
        amount=gross_exposure,
    )
    artifact = execute_postgres_ownership_change(
        request,
        lambda repository, _tenant: OwnershipChangeApplicationService(repository).prepare_and_persist(
            domain_request,
            actor_label=current_user.id,
        ),
    )
    return {
        "artifact": artifact,
        "source": {"kind": "postgresql-consolidation-ownership-change", "server_mode": True},
    }


@router.get("/{artifact_id}")
def get_ownership_change(
    artifact_id: Annotated[str, Path(pattern=r"^ownchg-[0-9a-f]{32}$")],
    request: Request,
    current_user: OwnershipChangeRead,
) -> dict[str, object]:
    """Return one tenant-scoped, replay-verified ownership-change artifact."""

    _server_only(request)
    _enforce_server_policy(request, permissions=frozenset({"finance_core.read", "finance_core.manage"}))
    artifact = execute_postgres_ownership_change(
        request,
        lambda repository, _tenant: repository.get(artifact_id, actor_label=current_user.id),
    )
    return {
        "artifact": artifact,
        "source": {"kind": "postgresql-consolidation-ownership-change", "server_mode": True},
    }


__all__ = [
    "OwnershipChangeMoneyRequest",
    "OwnershipChangePrepareRequest",
    "get_ownership_change",
    "prepare_ownership_change",
    "router",
]
