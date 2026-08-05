"""Authenticated PostgreSQL API for non-posting acquisition deferred-tax evidence."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import enforce_server_scoped_permissions, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_consolidation_deferred_tax import (
    execute_postgres_deferred_tax,
    server_deferred_tax_enabled,
)
from reconforge.application.consolidation_deferred_tax import AcquisitionDeferredTaxApplicationService
from reconforge.auth.models import LocalUser
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_deferred_tax import (
    AcquisitionDeferredTaxBridgeRequest,
    AcquisitionDeferredTaxItem,
)
from reconforge.utils.money import Money

router = APIRouter(prefix="/consolidation-deferred-tax", tags=["consolidation-deferred-tax"])
DeferredTaxRead = Annotated[LocalUser, Depends(require_any_permission({"finance_core.read", "finance_core.manage"}))]
DeferredTaxPrepare = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]


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


class DeferredTaxItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    item_id: str = Field(min_length=1, max_length=160)
    item_kind: Literal["asset", "liability"]
    account_code: str = Field(min_length=1, max_length=160)
    fair_value: CanonicalMoneyRequest
    tax_basis: CanonicalMoneyRequest
    tax_rate: str = Field(min_length=1, max_length=64)
    source_reference: str = Field(min_length=1, max_length=160)
    tax_basis_reference: str = Field(min_length=1, max_length=160)


class DeferredTaxPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    acquisition_id: str = Field(min_length=1, max_length=160)
    subsidiary_entity_code: str = Field(min_length=1, max_length=160)
    period_id: str = Field(min_length=1, max_length=160)
    acquisition_date: str = Field(min_length=10, max_length=10)
    reporting_currency: str = Field(min_length=1, max_length=8)
    items: list[DeferredTaxItemRequest] = Field(min_length=1, max_length=4096)
    deferred_tax_asset_account_code: str = Field(min_length=1, max_length=160)
    deferred_tax_liability_account_code: str = Field(min_length=1, max_length=160)
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
                code="consolidation_deferred_tax_request_invalid",
                message="Deferred-tax monetary input is not a valid canonical Money value.",
            ) from exc

    def to_domain(self, *, prepared_by: str) -> AcquisitionDeferredTaxBridgeRequest:
        try:
            return AcquisitionDeferredTaxBridgeRequest(
                acquisition_id=self.acquisition_id,
                subsidiary_entity_code=self.subsidiary_entity_code,
                period_id=self.period_id,
                acquisition_date=self.acquisition_date,
                reporting_currency=self.reporting_currency,
                items=tuple(
                    AcquisitionDeferredTaxItem(
                        item_id=item.item_id,
                        item_kind=item.item_kind,
                        account_code=item.account_code,
                        fair_value=self._money(item.fair_value),
                        tax_basis=self._money(item.tax_basis),
                        tax_rate=Decimal(item.tax_rate),
                        source_reference=item.source_reference,
                        tax_basis_reference=item.tax_basis_reference,
                    )
                    for item in self.items
                ),
                deferred_tax_asset_account_code=self.deferred_tax_asset_account_code,
                deferred_tax_liability_account_code=self.deferred_tax_liability_account_code,
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
        except (ConsolidationError, InvalidOperation, TypeError, ValueError) as exc:
            raise APIError(
                status_code=400,
                code="consolidation_deferred_tax_request_invalid",
                message="Deferred-tax request failed deterministic validation.",
            ) from exc


def _server_only(request: Request) -> None:
    if not server_deferred_tax_enabled(request):
        raise APIError(
            status_code=503,
            code="consolidation_deferred_tax_unavailable",
            message="Consolidation deferred-tax persistence requires the PostgreSQL server profile.",
        )


def _enforce_server_policy(request: Request, *, permissions: frozenset[str]) -> None:
    """Re-evaluate tenant policy before accessing tenant-scoped evidence."""

    from reconforge.api.server_identity import request_tenant_id

    enforce_server_scoped_permissions(
        request,
        permissions=permissions,
        tenant_id=request_tenant_id(request),
        workspace_id=None,
    )


@router.post("")
def prepare_deferred_tax(
    request: Request,
    payload: DeferredTaxPrepareRequest,
    current_user: DeferredTaxPrepare,
) -> dict[str, object]:
    """Persist one authenticated, maker-checker, non-posting deferred-tax artifact."""

    _server_only(request)
    _enforce_server_policy(request, permissions=frozenset({"finance_core.manage"}))
    domain_request = payload.to_domain(prepared_by=current_user.id)
    artifact = execute_postgres_deferred_tax(
        request,
        lambda repository, _tenant: AcquisitionDeferredTaxApplicationService(repository).prepare_and_persist(
            domain_request,
            actor_label=current_user.id,
        ),
    )
    return {
        "artifact": artifact,
        "source": {"kind": "postgresql-consolidation-deferred-tax", "server_mode": True},
    }


@router.get("/{artifact_id}")
def get_deferred_tax(
    artifact_id: str,
    request: Request,
    current_user: DeferredTaxRead,
) -> dict[str, object]:
    """Return one tenant-scoped, replay-verified deferred-tax artifact."""

    _server_only(request)
    _enforce_server_policy(request, permissions=frozenset({"finance_core.read", "finance_core.manage"}))
    artifact = execute_postgres_deferred_tax(
        request,
        lambda repository, _tenant: repository.get(artifact_id, actor_label=current_user.id),
    )
    return {
        "artifact": artifact,
        "source": {"kind": "postgresql-consolidation-deferred-tax", "server_mode": True},
    }


__all__ = [
    "CanonicalMoneyRequest",
    "DeferredTaxItemRequest",
    "DeferredTaxPrepareRequest",
    "get_deferred_tax",
    "prepare_deferred_tax",
    "router",
]
