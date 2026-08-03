"""Authenticated PostgreSQL API for non-posting acquisition PPA evidence."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_consolidation_ppa import execute_postgres_ppa, server_ppa_enabled
from reconforge.application.consolidation_ppa import AcquisitionPpaApplicationService
from reconforge.auth.models import LocalUser
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_ppa import (
    AcquisitionPpaItem,
    AcquisitionPurchasePriceAllocationRequest,
)
from reconforge.utils.money import Money

router = APIRouter(prefix="/consolidation-ppa", tags=["consolidation-ppa"])
PpaRead = Annotated[LocalUser, Depends(require_any_permission({"finance_core.read", "finance_core.manage"}))]
PpaPrepare = Annotated[LocalUser, Depends(require_permission("finance_core.manage"))]


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


class PpaItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    item_id: str = Field(min_length=1, max_length=160)
    item_kind: Literal["asset", "liability"]
    class_code: str = Field(min_length=1, max_length=160)
    account_code: str = Field(min_length=1, max_length=160)
    book_value: CanonicalMoneyRequest
    fair_value: CanonicalMoneyRequest
    valuation_reference: str = Field(min_length=1, max_length=160)
    source_reference: str = Field(min_length=1, max_length=160)


class PpaPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    acquisition_id: str = Field(min_length=1, max_length=160)
    subsidiary_entity_code: str = Field(min_length=1, max_length=160)
    period_id: str = Field(min_length=1, max_length=160)
    acquisition_date: str = Field(min_length=10, max_length=10)
    reporting_currency: str = Field(min_length=1, max_length=8)
    consideration: CanonicalMoneyRequest
    nci_fair_value: CanonicalMoneyRequest
    items: list[PpaItemRequest] = Field(min_length=1, max_length=4096)
    allow_bargain_purchase: bool
    consideration_account_code: str = Field(min_length=1, max_length=160)
    nci_account_code: str = Field(min_length=1, max_length=160)
    identifiable_net_assets_account_code: str = Field(min_length=1, max_length=160)
    goodwill_account_code: str = Field(min_length=1, max_length=160)
    bargain_purchase_account_code: str = Field(min_length=1, max_length=160)
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
                code="consolidation_ppa_request_invalid",
                message="PPA monetary input is not a valid canonical Money value.",
            ) from exc

    def to_domain(self, *, prepared_by: str) -> AcquisitionPurchasePriceAllocationRequest:
        try:
            return AcquisitionPurchasePriceAllocationRequest(
                acquisition_id=self.acquisition_id,
                subsidiary_entity_code=self.subsidiary_entity_code,
                period_id=self.period_id,
                acquisition_date=self.acquisition_date,
                reporting_currency=self.reporting_currency,
                consideration=self._money(self.consideration),
                nci_fair_value=self._money(self.nci_fair_value),
                items=tuple(
                    AcquisitionPpaItem(
                        item_id=item.item_id,
                        item_kind=item.item_kind,
                        class_code=item.class_code,
                        account_code=item.account_code,
                        book_value=self._money(item.book_value),
                        fair_value=self._money(item.fair_value),
                        valuation_reference=item.valuation_reference,
                        source_reference=item.source_reference,
                    )
                    for item in self.items
                ),
                allow_bargain_purchase=self.allow_bargain_purchase,
                consideration_account_code=self.consideration_account_code,
                nci_account_code=self.nci_account_code,
                identifiable_net_assets_account_code=self.identifiable_net_assets_account_code,
                goodwill_account_code=self.goodwill_account_code,
                bargain_purchase_account_code=self.bargain_purchase_account_code,
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
                code="consolidation_ppa_request_invalid",
                message="PPA request failed deterministic validation.",
            ) from exc


def _server_only(request: Request) -> None:
    if not server_ppa_enabled(request):
        raise APIError(
            status_code=503,
            code="consolidation_ppa_unavailable",
            message="Consolidation PPA persistence requires the PostgreSQL server profile.",
        )


@router.post("")
def prepare_ppa(
    request: Request,
    payload: PpaPrepareRequest,
    current_user: PpaPrepare,
) -> dict[str, object]:
    """Persist one authenticated, maker-checker, non-posting PPA artifact."""

    _server_only(request)
    domain_request = payload.to_domain(prepared_by=current_user.id)
    artifact = execute_postgres_ppa(
        request,
        lambda repository, _tenant: AcquisitionPpaApplicationService(repository).prepare_and_persist(
            domain_request,
            actor_label=current_user.id,
        ),
    )
    return {"artifact": artifact, "source": {"kind": "postgresql-consolidation-ppa", "server_mode": True}}


@router.get("/{artifact_id}")
def get_ppa(
    artifact_id: str,
    request: Request,
    current_user: PpaRead,
) -> dict[str, object]:
    """Return one tenant-scoped, replay-verified PPA artifact."""

    _server_only(request)
    artifact = execute_postgres_ppa(
        request,
        lambda repository, _tenant: repository.get(artifact_id, actor_label=current_user.id),
    )
    return {"artifact": artifact, "source": {"kind": "postgresql-consolidation-ppa", "server_mode": True}}


__all__ = ["CanonicalMoneyRequest", "PpaItemRequest", "PpaPrepareRequest", "get_ppa", "prepare_ppa", "router"]
