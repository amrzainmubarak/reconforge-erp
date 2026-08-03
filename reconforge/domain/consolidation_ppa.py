"""Deterministic, non-posting acquisition purchase-price allocation (PPA).

The PPA artifact makes the identifiable-asset/liability fair-value bridge
reviewable before a separate statutory accounting decision.  It deliberately
does not post journals, decide tax/impairment treatment, or infer a valuation
from incomplete inputs.  All values are exact ``Money`` instances and the
result embeds the existing acquisition fair-value/goodwill bridge.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from typing import Literal

from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_acquisition import (
    AcquisitionFairValueBridgeRequest,
    AcquisitionFairValueBridgeResult,
    prepare_acquisition_fair_value_bridge,
    verify_acquisition_fair_value_bridge_payload,
)
from reconforge.utils.money import Money

ACQUISITION_PPA_SCHEMA_VERSION = 1
ACQUISITION_PPA_ALGORITHM_VERSION = "acquisition-purchase-price-allocation-v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_SEMVER = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")

AcquisitionPpaItemKind = Literal["asset", "liability"]


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise ConsolidationError(f"{field} is invalid.")
    return value.strip()


def _semver(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SEMVER.fullmatch(value):
        raise ConsolidationError(f"{field} must be semantic versioning.")
    return value


def _date(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ConsolidationError(f"{field} must be an ISO-8601 date.")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise ConsolidationError(f"{field} must be an ISO-8601 date.") from exc


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConsolidationError(f"{field} must be a timezone-aware ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConsolidationError(f"{field} must be a timezone-aware ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.microsecond:
        raise ConsolidationError(f"{field} must use whole-second timezone-aware precision.")
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _money(value: object, currency: str, field: str, *, non_negative: bool = True) -> Money:
    if not isinstance(value, Money) or value.currency != currency or not value.amount.is_finite():
        raise ConsolidationError(f"Acquisition PPA {field} must use the reporting currency and be finite.")
    if non_negative and value.amount < 0:
        raise ConsolidationError(f"Acquisition PPA {field} must not be negative.")
    return value


def _add(*values: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = max(28, sum(len(value.as_tuple().digits) for value in values) + 4)
        return sum(values, Decimal("0"))


def _signed(kind: AcquisitionPpaItemKind, value: Decimal) -> Decimal:
    return value if kind == "asset" else -value


@dataclass(frozen=True)
class AcquisitionPpaItem:
    """One independently sourced asset or liability valuation input."""

    item_id: str
    item_kind: AcquisitionPpaItemKind
    class_code: str
    account_code: str
    book_value: Money
    fair_value: Money
    valuation_reference: str
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _identifier(self.item_id, "Acquisition PPA item"))
        if self.item_kind not in {"asset", "liability"}:
            raise ConsolidationError("Acquisition PPA item kind must be asset or liability.")
        object.__setattr__(self, "class_code", _identifier(self.class_code, "Acquisition PPA class"))
        object.__setattr__(self, "account_code", _identifier(self.account_code, "Acquisition PPA account"))
        object.__setattr__(self, "valuation_reference", _identifier(self.valuation_reference, "Acquisition valuation reference"))
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "Acquisition PPA source reference"))
        for field in ("book_value", "fair_value"):
            value = getattr(self, field)
            if not isinstance(value, Money) or not value.amount.is_finite() or value.amount < 0:
                raise ConsolidationError(f"Acquisition PPA {field} must be finite and non-negative Money.")

    def signed_book_value(self) -> Decimal:
        return _signed(self.item_kind, self.book_value.amount)

    def signed_fair_value(self) -> Decimal:
        return _signed(self.item_kind, self.fair_value.amount)

    def signed_adjustment(self, currency: str) -> Money:
        return Money.from_exact(
            self.signed_fair_value() - self.signed_book_value(),
            currency,
            strict_precision=True,
        )

    def to_dict(self, *, currency: str) -> dict[str, object]:
        return {
            "account_code": self.account_code,
            "book_value": self.book_value.to_canonical_dict(),
            "class_code": self.class_code,
            "fair_value": self.fair_value.to_canonical_dict(),
            "fair_value_adjustment": self.signed_adjustment(currency).to_canonical_dict(),
            "item_id": self.item_id,
            "item_kind": self.item_kind,
            "source_reference": self.source_reference,
            "valuation_reference": self.valuation_reference,
        }

    def to_input_dict(self) -> dict[str, object]:
        """Return the closed source-input shape without derived adjustments."""

        return {
            "account_code": self.account_code,
            "book_value": self.book_value.to_canonical_dict(),
            "class_code": self.class_code,
            "fair_value": self.fair_value.to_canonical_dict(),
            "item_id": self.item_id,
            "item_kind": self.item_kind,
            "source_reference": self.source_reference,
            "valuation_reference": self.valuation_reference,
        }


@dataclass(frozen=True)
class AcquisitionPurchasePriceAllocationRequest:
    """Source-bound PPA inputs for one non-posting acquisition artifact."""

    acquisition_id: str
    subsidiary_entity_code: str
    period_id: str
    acquisition_date: str
    reporting_currency: str
    consideration: Money
    nci_fair_value: Money
    items: tuple[AcquisitionPpaItem, ...]
    allow_bargain_purchase: bool
    consideration_account_code: str
    nci_account_code: str
    identifiable_net_assets_account_code: str
    goodwill_account_code: str
    bargain_purchase_account_code: str
    policy_id: str
    policy_version: str
    source_reference: str
    source_digest: str
    prepared_by: str
    prepared_at: str
    approved_by: str
    approved_at: str

    def __post_init__(self) -> None:
        for field in ("acquisition_id", "subsidiary_entity_code", "period_id"):
            object.__setattr__(self, field, _identifier(getattr(self, field), field.replace("_", " ")))
        object.__setattr__(self, "acquisition_date", _date(self.acquisition_date, "Acquisition date"))
        currency = self.reporting_currency.strip().upper() if isinstance(self.reporting_currency, str) else ""
        if not re.fullmatch(r"[A-Z][A-Z0-9]{2,5}", currency):
            raise ConsolidationError("Acquisition PPA reporting currency is invalid.")
        object.__setattr__(self, "reporting_currency", currency)
        for field in ("consideration", "nci_fair_value"):
            object.__setattr__(self, field, _money(getattr(self, field), currency, field))
        if not isinstance(self.items, tuple) or not self.items or len(self.items) > 4096:
            raise ConsolidationError("Acquisition PPA requires between one and 4096 valuation items.")
        item_ids: set[str] = set()
        for item in self.items:
            if not isinstance(item, AcquisitionPpaItem):
                raise ConsolidationError("Acquisition PPA items must use the typed item contract.")
            if item.item_id in item_ids:
                raise ConsolidationError("Acquisition PPA item IDs must be unique.")
            item_ids.add(item.item_id)
            for field in ("book_value", "fair_value"):
                _money(getattr(item, field), currency, f"item {item.item_id} {field}")
        object.__setattr__(self, "items", tuple(sorted(self.items, key=lambda item: item.item_id)))
        account_fields = (
            "consideration_account_code",
            "nci_account_code",
            "identifiable_net_assets_account_code",
            "goodwill_account_code",
            "bargain_purchase_account_code",
        )
        for field in account_fields:
            object.__setattr__(self, field, _identifier(getattr(self, field), field.replace("_", " ")))
        if len({getattr(self, field) for field in account_fields}) != len(account_fields):
            raise ConsolidationError("Acquisition PPA accounts must be distinct.")
        if not isinstance(self.allow_bargain_purchase, bool):
            raise ConsolidationError("Acquisition PPA bargain-purchase policy must be boolean.")
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "Acquisition PPA policy"))
        object.__setattr__(self, "policy_version", _semver(self.policy_version, "Acquisition PPA policy version"))
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "Acquisition PPA source reference"))
        if not isinstance(self.source_digest, str) or not _SHA256.fullmatch(self.source_digest):
            raise ConsolidationError("Acquisition PPA source digest must be a lowercase SHA-256 digest.")
        object.__setattr__(self, "prepared_by", _identifier(self.prepared_by, "Acquisition PPA preparer"))
        object.__setattr__(self, "approved_by", _identifier(self.approved_by, "Acquisition PPA approver"))
        if self.prepared_by == self.approved_by:
            raise ConsolidationError("Acquisition PPA preparation and approval require different actors.")
        prepared_at = _timestamp(self.prepared_at, "Acquisition PPA preparation timestamp")
        approved_at = _timestamp(self.approved_at, "Acquisition PPA approval timestamp")
        if approved_at > prepared_at:
            raise ConsolidationError("Acquisition PPA approval must precede proposal preparation.")
        object.__setattr__(self, "prepared_at", prepared_at)
        object.__setattr__(self, "approved_at", approved_at)

    @property
    def book_net_assets(self) -> Money:
        return Money.from_exact(
            _add(*(item.signed_book_value() for item in self.items)),
            self.reporting_currency,
            strict_precision=True,
        )

    @property
    def fair_value_net_assets(self) -> Money:
        amount = _add(*(item.signed_fair_value() for item in self.items))
        if amount < 0:
            raise ConsolidationError("Acquisition PPA identifiable fair-value net assets cannot be negative.")
        return Money.from_exact(amount, self.reporting_currency, strict_precision=True)

    def to_dict(self) -> dict[str, object]:
        return {
            "acquisition_date": self.acquisition_date,
            "acquisition_id": self.acquisition_id,
            "allow_bargain_purchase": self.allow_bargain_purchase,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "bargain_purchase_account_code": self.bargain_purchase_account_code,
            "consideration": self.consideration.to_canonical_dict(),
            "consideration_account_code": self.consideration_account_code,
            "goodwill_account_code": self.goodwill_account_code,
            "identifiable_net_assets_account_code": self.identifiable_net_assets_account_code,
            "items": [item.to_input_dict() for item in self.items],
            "nci_account_code": self.nci_account_code,
            "nci_fair_value": self.nci_fair_value.to_canonical_dict(),
            "period_id": self.period_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "prepared_at": self.prepared_at,
            "prepared_by": self.prepared_by,
            "reporting_currency": self.reporting_currency,
            "source_digest": self.source_digest,
            "source_reference": self.source_reference,
            "subsidiary_entity_code": self.subsidiary_entity_code,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class AcquisitionPurchasePriceAllocationResult:
    schema_version: int
    algorithm_version: str
    request_digest: str
    result_digest: str
    acquisition_id: str
    reporting_currency: str
    book_net_assets: Money
    fair_value_net_assets: Money
    fair_value_adjustment: Money
    items: tuple[AcquisitionPpaItem, ...]
    bridge: AcquisitionFairValueBridgeResult
    posted: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "acquisition_id": self.acquisition_id,
            "algorithm_version": self.algorithm_version,
            "book_net_assets": self.book_net_assets.to_canonical_dict(),
            "bridge": self.bridge.to_dict(),
            "fair_value_adjustment": self.fair_value_adjustment.to_canonical_dict(),
            "fair_value_net_assets": self.fair_value_net_assets.to_canonical_dict(),
            "items": [item.to_dict(currency=self.reporting_currency) for item in self.items],
            "posted": self.posted,
            "reporting_currency": self.reporting_currency,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "schema_version": self.schema_version,
        }


def prepare_acquisition_purchase_price_allocation(
    request: AcquisitionPurchasePriceAllocationRequest,
) -> AcquisitionPurchasePriceAllocationResult:
    """Build a balanced, explainable, non-posting PPA and goodwill bridge."""

    if not isinstance(request, AcquisitionPurchasePriceAllocationRequest):
        raise ConsolidationError("An acquisition purchase-price allocation request is required.")
    fair_value_net_assets = request.fair_value_net_assets
    bridge_request = AcquisitionFairValueBridgeRequest(
        acquisition_id=request.acquisition_id,
        subsidiary_entity_code=request.subsidiary_entity_code,
        period_id=request.period_id,
        acquisition_date=request.acquisition_date,
        reporting_currency=request.reporting_currency,
        consideration=request.consideration,
        nci_fair_value=request.nci_fair_value,
        identifiable_net_assets_fair_value=fair_value_net_assets,
        allow_bargain_purchase=request.allow_bargain_purchase,
        consideration_account_code=request.consideration_account_code,
        nci_account_code=request.nci_account_code,
        identifiable_net_assets_account_code=request.identifiable_net_assets_account_code,
        goodwill_account_code=request.goodwill_account_code,
        bargain_purchase_account_code=request.bargain_purchase_account_code,
        policy_id=request.policy_id,
        policy_version=request.policy_version,
        source_reference=request.source_reference,
        source_digest=request.source_digest,
        prepared_by=request.prepared_by,
        prepared_at=request.prepared_at,
        approved_by=request.approved_by,
        approved_at=request.approved_at,
    )
    bridge = prepare_acquisition_fair_value_bridge(bridge_request)
    book_net_assets = request.book_net_assets
    fair_value_adjustment = Money.from_exact(
        fair_value_net_assets.amount - book_net_assets.amount,
        request.reporting_currency,
        strict_precision=True,
    )
    unsigned: dict[str, object] = {
        "acquisition_id": request.acquisition_id,
        "algorithm_version": ACQUISITION_PPA_ALGORITHM_VERSION,
        "book_net_assets": book_net_assets.to_canonical_dict(),
        "bridge": bridge.to_dict(),
        "fair_value_adjustment": fair_value_adjustment.to_canonical_dict(),
        "fair_value_net_assets": fair_value_net_assets.to_canonical_dict(),
        "items": [item.to_dict(currency=request.reporting_currency) for item in request.items],
        "posted": False,
        "reporting_currency": request.reporting_currency,
        "request_digest": request.digest,
        "schema_version": ACQUISITION_PPA_SCHEMA_VERSION,
    }
    return AcquisitionPurchasePriceAllocationResult(
        schema_version=ACQUISITION_PPA_SCHEMA_VERSION,
        algorithm_version=ACQUISITION_PPA_ALGORITHM_VERSION,
        request_digest=request.digest,
        result_digest=_digest(unsigned),
        acquisition_id=request.acquisition_id,
        reporting_currency=request.reporting_currency,
        book_net_assets=book_net_assets,
        fair_value_net_assets=fair_value_net_assets,
        fair_value_adjustment=fair_value_adjustment,
        items=request.items,
        bridge=bridge,
    )


def _canonical_money(payload: object, currency: str, field: str, *, non_negative: bool = False) -> Money:
    try:
        value = Money.from_canonical_dict(payload)  # type: ignore[arg-type]
    except (TypeError, ValueError, KeyError) as exc:
        raise ConsolidationError(f"Acquisition PPA {field} money is invalid.") from exc
    return _money(value, currency, field, non_negative=non_negative)


def verify_acquisition_purchase_price_allocation_payload(payload: object) -> dict[str, object]:
    """Verify PPA digest, item arithmetic, and the embedded bridge."""

    if not isinstance(payload, dict):
        raise ConsolidationError("Acquisition PPA payload must be an object.")
    expected_digest = payload.get("result_digest")
    if not isinstance(expected_digest, str) or not _SHA256.fullmatch(expected_digest):
        raise ConsolidationError("Acquisition PPA result digest is missing or invalid.")
    unsigned = dict(payload)
    unsigned.pop("result_digest", None)
    if _digest(unsigned) != expected_digest:
        raise ConsolidationError("Acquisition PPA result digest mismatch.")
    if payload.get("schema_version") != ACQUISITION_PPA_SCHEMA_VERSION:
        raise ConsolidationError("Acquisition PPA schema version is unsupported.")
    if payload.get("algorithm_version") != ACQUISITION_PPA_ALGORITHM_VERSION:
        raise ConsolidationError("Acquisition PPA algorithm version is unsupported.")
    if payload.get("posted") is not False:
        raise ConsolidationError("Acquisition PPA cannot be posted.")
    acquisition_id = payload.get("acquisition_id")
    currency = payload.get("reporting_currency")
    if not isinstance(acquisition_id, str) or not isinstance(currency, str):
        raise ConsolidationError("Acquisition PPA identity is invalid.")
    book_net = _canonical_money(payload.get("book_net_assets"), currency, "book net assets")
    fair_net = _canonical_money(payload.get("fair_value_net_assets"), currency, "fair-value net assets", non_negative=True)
    adjustment = _canonical_money(payload.get("fair_value_adjustment"), currency, "fair-value adjustment")
    if adjustment.amount != fair_net.amount - book_net.amount:
        raise ConsolidationError("Acquisition PPA fair-value adjustment does not reconcile.")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > 4096:
        raise ConsolidationError("Acquisition PPA items are invalid.")
    seen: set[str] = set()
    book_total = Decimal("0")
    fair_total = Decimal("0")
    item_fields = {
        "account_code",
        "book_value",
        "class_code",
        "fair_value",
        "fair_value_adjustment",
        "item_id",
        "item_kind",
        "source_reference",
        "valuation_reference",
    }
    for raw_item in raw_items:
        if not isinstance(raw_item, dict) or set(raw_item) != item_fields:
            raise ConsolidationError("Acquisition PPA item fields are not exactly declared.")
        item_id = raw_item.get("item_id")
        item_kind = raw_item.get("item_kind")
        if not isinstance(item_id, str) or item_id in seen or item_kind not in {"asset", "liability"}:
            raise ConsolidationError("Acquisition PPA item identity or kind is invalid.")
        seen.add(item_id)
        book = _canonical_money(raw_item.get("book_value"), currency, f"item {item_id} book value", non_negative=True)
        fair = _canonical_money(raw_item.get("fair_value"), currency, f"item {item_id} fair value", non_negative=True)
        item_adjustment = _canonical_money(
            raw_item.get("fair_value_adjustment"), currency, f"item {item_id} fair-value adjustment"
        )
        sign = Decimal("1") if item_kind == "asset" else Decimal("-1")
        book_total += sign * book.amount
        fair_total += sign * fair.amount
        if item_adjustment.amount != sign * (fair.amount - book.amount):
            raise ConsolidationError(f"Acquisition PPA item {item_id} adjustment does not reconcile.")
    if book_total != book_net.amount or fair_total != fair_net.amount:
        raise ConsolidationError("Acquisition PPA item totals do not reconcile to net assets.")
    bridge = payload.get("bridge")
    if not isinstance(bridge, dict):
        raise ConsolidationError("Acquisition PPA embedded bridge is missing.")
    verify_acquisition_fair_value_bridge_payload(bridge)
    if bridge.get("acquisition_id") != acquisition_id or bridge.get("reporting_currency") != currency:
        raise ConsolidationError("Acquisition PPA embedded bridge identity does not match.")
    bridge_lines = bridge.get("lines")
    if not isinstance(bridge_lines, list):
        raise ConsolidationError("Acquisition PPA embedded bridge lines are invalid.")
    net_lines = [line for line in bridge_lines if isinstance(line, dict) and line.get("line_type") == "identifiable_net_assets"]
    if len(net_lines) != 1:
        raise ConsolidationError("Acquisition PPA embedded bridge net-assets line is invalid.")
    net_amount = _canonical_money(net_lines[0].get("amount"), currency, "embedded net-assets line")
    if net_amount.amount != -fair_net.amount:
        raise ConsolidationError("Acquisition PPA embedded bridge net-assets line does not reconcile.")
    return dict(payload)


__all__ = [
    "ACQUISITION_PPA_ALGORITHM_VERSION",
    "ACQUISITION_PPA_SCHEMA_VERSION",
    "AcquisitionPpaItem",
    "AcquisitionPpaItemKind",
    "AcquisitionPurchasePriceAllocationRequest",
    "AcquisitionPurchasePriceAllocationResult",
    "prepare_acquisition_purchase_price_allocation",
    "verify_acquisition_purchase_price_allocation_payload",
]
