"""Deterministic, non-posting acquisition deferred-tax bridge.

This module calculates temporary differences from approved acquisition inputs.
It is deliberately not a statutory tax engine: it does not decide recognition,
tax-law applicability, valuation allowances, or post a journal.  The result is
an exact, source-bound artifact that a separate close workflow can review.
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
from reconforge.utils.money import Money, parse_exact_amount

ACQUISITION_DEFERRED_TAX_SCHEMA_VERSION = 1
ACQUISITION_DEFERRED_TAX_ALGORITHM_VERSION = "acquisition-deferred-tax-bridge-v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_SEMVER = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")

DeferredTaxItemKind = Literal["asset", "liability"]
DeferredTaxClassification = Literal["deferred_tax_asset", "deferred_tax_liability", "none"]


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


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ConsolidationError("Acquisition deferred-tax decimals must be finite.")
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _decimal(value: object, field: str, *, minimum: Decimal, maximum: Decimal) -> Decimal:
    if isinstance(value, (bool, float)):
        raise ConsolidationError(f"{field} must use an exact decimal value.")
    try:
        parsed = parse_exact_amount(value)
    except (TypeError, ValueError) as exc:
        raise ConsolidationError(f"{field} must use an exact decimal value.") from exc
    if not parsed.is_finite() or parsed < minimum or parsed > maximum:
        raise ConsolidationError(f"{field} is outside the supported range.")
    return parsed


def _money(value: object, currency: str, field: str, *, non_negative: bool = False) -> Money:
    if not isinstance(value, Money) or value.currency != currency or not value.amount.is_finite():
        raise ConsolidationError(f"Acquisition deferred-tax {field} must use the reporting currency and be finite.")
    if non_negative and value.amount < 0:
        raise ConsolidationError(f"Acquisition deferred-tax {field} must not be negative.")
    return value


def _add(*values: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = max(28, sum(len(value.as_tuple().digits) for value in values) + 4)
        return sum(values, Decimal("0"))


def _signed(kind: DeferredTaxItemKind, value: Decimal) -> Decimal:
    return value if kind == "asset" else -value


@dataclass(frozen=True)
class AcquisitionDeferredTaxItem:
    """One source-bound temporary-difference input."""

    item_id: str
    item_kind: DeferredTaxItemKind
    account_code: str
    fair_value: Money
    tax_basis: Money
    tax_rate: Decimal
    source_reference: str
    tax_basis_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _identifier(self.item_id, "Acquisition deferred-tax item"))
        if self.item_kind not in {"asset", "liability"}:
            raise ConsolidationError("Acquisition deferred-tax item kind must be asset or liability.")
        object.__setattr__(self, "account_code", _identifier(self.account_code, "Acquisition deferred-tax account"))
        for field in ("fair_value", "tax_basis"):
            value = getattr(self, field)
            if not isinstance(value, Money) or not value.amount.is_finite() or value.amount < 0:
                raise ConsolidationError(f"Acquisition deferred-tax {field} must be finite and non-negative Money.")
        object.__setattr__(
            self,
            "tax_rate",
            _decimal(self.tax_rate, "Acquisition deferred-tax tax rate", minimum=Decimal("0"), maximum=Decimal("1")),
        )
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "Acquisition deferred-tax source"))
        object.__setattr__(
            self,
            "tax_basis_reference",
            _identifier(self.tax_basis_reference, "Acquisition deferred-tax basis reference"),
        )

    def signed_fair_value(self) -> Decimal:
        return _signed(self.item_kind, self.fair_value.amount)

    def signed_tax_basis(self) -> Decimal:
        return _signed(self.item_kind, self.tax_basis.amount)

    def temporary_difference(self, currency: str) -> Money:
        return Money.from_exact(self.signed_fair_value() - self.signed_tax_basis(), currency, strict_precision=True)

    def tax_effect(self, currency: str) -> Money:
        # Money applies the installed currency registry's explicit ROUND_HALF_UP policy.
        return Money.from_exact(self.temporary_difference(currency).amount * self.tax_rate, currency)

    def classification(self, currency: str) -> DeferredTaxClassification:
        amount = self.tax_effect(currency).amount
        if amount > 0:
            return "deferred_tax_liability"
        if amount < 0:
            return "deferred_tax_asset"
        return "none"

    def to_input_dict(self) -> dict[str, object]:
        return {
            "account_code": self.account_code,
            "fair_value": self.fair_value.to_canonical_dict(),
            "item_id": self.item_id,
            "item_kind": self.item_kind,
            "source_reference": self.source_reference,
            "tax_basis": self.tax_basis.to_canonical_dict(),
            "tax_basis_reference": self.tax_basis_reference,
            "tax_rate": _decimal_text(self.tax_rate),
        }

    def to_dict(self, *, currency: str) -> dict[str, object]:
        tax_effect = self.tax_effect(currency)
        return {
            **self.to_input_dict(),
            "classification": self.classification(currency),
            "tax_amount": tax_effect.to_canonical_dict(),
            "temporary_difference": self.temporary_difference(currency).to_canonical_dict(),
        }


@dataclass(frozen=True)
class AcquisitionDeferredTaxBridgeRequest:
    """Approved inputs for a non-posting acquisition deferred-tax artifact."""

    acquisition_id: str
    subsidiary_entity_code: str
    period_id: str
    acquisition_date: str
    reporting_currency: str
    items: tuple[AcquisitionDeferredTaxItem, ...]
    deferred_tax_asset_account_code: str
    deferred_tax_liability_account_code: str
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
        object.__setattr__(self, "acquisition_date", _date(self.acquisition_date, "Acquisition deferred-tax date"))
        currency = self.reporting_currency.strip().upper() if isinstance(self.reporting_currency, str) else ""
        if not re.fullmatch(r"[A-Z][A-Z0-9]{2,5}", currency):
            raise ConsolidationError("Acquisition deferred-tax reporting currency is invalid.")
        object.__setattr__(self, "reporting_currency", currency)
        if not isinstance(self.items, tuple) or not self.items or len(self.items) > 4096:
            raise ConsolidationError("Acquisition deferred-tax requires between one and 4096 items.")
        item_ids: set[str] = set()
        for item in self.items:
            if not isinstance(item, AcquisitionDeferredTaxItem):
                raise ConsolidationError("Acquisition deferred-tax items must use the typed item contract.")
            if item.item_id in item_ids:
                raise ConsolidationError("Acquisition deferred-tax item IDs must be unique.")
            item_ids.add(item.item_id)
            for field in ("fair_value", "tax_basis"):
                _money(getattr(item, field), currency, f"item {item.item_id} {field}", non_negative=True)
        object.__setattr__(self, "items", tuple(sorted(self.items, key=lambda item: item.item_id)))
        for field in ("deferred_tax_asset_account_code", "deferred_tax_liability_account_code"):
            object.__setattr__(self, field, _identifier(getattr(self, field), field.replace("_", " ")))
        if self.deferred_tax_asset_account_code == self.deferred_tax_liability_account_code:
            raise ConsolidationError("Acquisition deferred-tax asset and liability accounts must be distinct.")
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "Acquisition deferred-tax policy"))
        object.__setattr__(self, "policy_version", _semver(self.policy_version, "Acquisition deferred-tax policy version"))
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "Acquisition deferred-tax source reference"))
        if not isinstance(self.source_digest, str) or not _SHA256.fullmatch(self.source_digest):
            raise ConsolidationError("Acquisition deferred-tax source digest must be a lowercase SHA-256 digest.")
        object.__setattr__(self, "prepared_by", _identifier(self.prepared_by, "Acquisition deferred-tax preparer"))
        object.__setattr__(self, "approved_by", _identifier(self.approved_by, "Acquisition deferred-tax approver"))
        if self.prepared_by == self.approved_by:
            raise ConsolidationError("Acquisition deferred-tax preparation and approval require different actors.")
        prepared_at = _timestamp(self.prepared_at, "Acquisition deferred-tax preparation timestamp")
        approved_at = _timestamp(self.approved_at, "Acquisition deferred-tax approval timestamp")
        if approved_at > prepared_at:
            raise ConsolidationError("Acquisition deferred-tax approval must precede proposal preparation.")
        object.__setattr__(self, "prepared_at", prepared_at)
        object.__setattr__(self, "approved_at", approved_at)

    def to_dict(self) -> dict[str, object]:
        return {
            "acquisition_date": self.acquisition_date,
            "acquisition_id": self.acquisition_id,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "deferred_tax_asset_account_code": self.deferred_tax_asset_account_code,
            "deferred_tax_liability_account_code": self.deferred_tax_liability_account_code,
            "items": [item.to_input_dict() for item in self.items],
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
class AcquisitionDeferredTaxBridgeResult:
    schema_version: int
    algorithm_version: str
    request_digest: str
    result_digest: str
    acquisition_id: str
    reporting_currency: str
    deferred_tax_asset: Money
    deferred_tax_liability: Money
    net_deferred_tax: Money
    items: tuple[AcquisitionDeferredTaxItem, ...]
    posted: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "acquisition_id": self.acquisition_id,
            "algorithm_version": self.algorithm_version,
            "deferred_tax_asset": self.deferred_tax_asset.to_canonical_dict(),
            "deferred_tax_liability": self.deferred_tax_liability.to_canonical_dict(),
            "items": [item.to_dict(currency=self.reporting_currency) for item in self.items],
            "net_deferred_tax": self.net_deferred_tax.to_canonical_dict(),
            "posted": self.posted,
            "reporting_currency": self.reporting_currency,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "schema_version": self.schema_version,
        }


def prepare_acquisition_deferred_tax_bridge(
    request: AcquisitionDeferredTaxBridgeRequest,
) -> AcquisitionDeferredTaxBridgeResult:
    """Build a balanced, explainable, non-posting deferred-tax bridge."""

    if not isinstance(request, AcquisitionDeferredTaxBridgeRequest):
        raise ConsolidationError("An acquisition deferred-tax bridge request is required.")
    currency = request.reporting_currency
    asset_total = _add(
        *(-item.tax_effect(currency).amount for item in request.items if item.tax_effect(currency).amount < 0)
    )
    liability_total = _add(
        *(item.tax_effect(currency).amount for item in request.items if item.tax_effect(currency).amount > 0)
    )
    deferred_tax_asset = Money.from_exact(asset_total, currency, strict_precision=True)
    deferred_tax_liability = Money.from_exact(liability_total, currency, strict_precision=True)
    net_deferred_tax = Money.from_exact(liability_total - asset_total, currency, strict_precision=True)
    unsigned: dict[str, object] = {
        "acquisition_id": request.acquisition_id,
        "algorithm_version": ACQUISITION_DEFERRED_TAX_ALGORITHM_VERSION,
        "deferred_tax_asset": deferred_tax_asset.to_canonical_dict(),
        "deferred_tax_liability": deferred_tax_liability.to_canonical_dict(),
        "items": [item.to_dict(currency=currency) for item in request.items],
        "net_deferred_tax": net_deferred_tax.to_canonical_dict(),
        "posted": False,
        "reporting_currency": currency,
        "request_digest": request.digest,
        "schema_version": ACQUISITION_DEFERRED_TAX_SCHEMA_VERSION,
    }
    return AcquisitionDeferredTaxBridgeResult(
        schema_version=ACQUISITION_DEFERRED_TAX_SCHEMA_VERSION,
        algorithm_version=ACQUISITION_DEFERRED_TAX_ALGORITHM_VERSION,
        request_digest=request.digest,
        result_digest=_digest(unsigned),
        acquisition_id=request.acquisition_id,
        reporting_currency=currency,
        deferred_tax_asset=deferred_tax_asset,
        deferred_tax_liability=deferred_tax_liability,
        net_deferred_tax=net_deferred_tax,
        items=request.items,
    )


def _canonical_money(payload: object, currency: str, field: str, *, non_negative: bool = False) -> Money:
    try:
        value = Money.from_canonical_dict(payload)  # type: ignore[arg-type]
    except (TypeError, ValueError, KeyError) as exc:
        raise ConsolidationError(f"Acquisition deferred-tax {field} money is invalid.") from exc
    return _money(value, currency, field, non_negative=non_negative)


def verify_acquisition_deferred_tax_bridge_payload(payload: object) -> dict[str, object]:
    """Verify digest, item arithmetic, classifications, and totals."""

    if not isinstance(payload, dict):
        raise ConsolidationError("Acquisition deferred-tax payload must be an object.")
    expected_digest = payload.get("result_digest")
    if not isinstance(expected_digest, str) or not _SHA256.fullmatch(expected_digest):
        raise ConsolidationError("Acquisition deferred-tax result digest is missing or invalid.")
    unsigned = dict(payload)
    unsigned.pop("result_digest", None)
    if _digest(unsigned) != expected_digest:
        raise ConsolidationError("Acquisition deferred-tax result digest mismatch.")
    if payload.get("schema_version") != ACQUISITION_DEFERRED_TAX_SCHEMA_VERSION:
        raise ConsolidationError("Acquisition deferred-tax schema version is unsupported.")
    if payload.get("algorithm_version") != ACQUISITION_DEFERRED_TAX_ALGORITHM_VERSION:
        raise ConsolidationError("Acquisition deferred-tax algorithm version is unsupported.")
    if payload.get("posted") is not False:
        raise ConsolidationError("Acquisition deferred-tax bridge cannot be posted.")
    acquisition_id = payload.get("acquisition_id")
    currency = payload.get("reporting_currency")
    request_digest = payload.get("request_digest")
    if not isinstance(acquisition_id, str) or not isinstance(currency, str) or not _SHA256.fullmatch(str(request_digest)):
        raise ConsolidationError("Acquisition deferred-tax identity is invalid.")
    asset_total = _canonical_money(payload.get("deferred_tax_asset"), currency, "deferred-tax asset", non_negative=True)
    liability_total = _canonical_money(
        payload.get("deferred_tax_liability"), currency, "deferred-tax liability", non_negative=True
    )
    net_total = _canonical_money(payload.get("net_deferred_tax"), currency, "net deferred tax")
    if net_total.amount != liability_total.amount - asset_total.amount:
        raise ConsolidationError("Acquisition deferred-tax net total does not reconcile.")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > 4096:
        raise ConsolidationError("Acquisition deferred-tax items are invalid.")
    seen: set[str] = set()
    asset_sum = Decimal("0")
    liability_sum = Decimal("0")
    item_fields = {
        "account_code",
        "classification",
        "fair_value",
        "item_id",
        "item_kind",
        "source_reference",
        "tax_amount",
        "tax_basis",
        "tax_basis_reference",
        "tax_rate",
        "temporary_difference",
    }
    previous_id = ""
    for raw_item in raw_items:
        if not isinstance(raw_item, dict) or set(raw_item) != item_fields:
            raise ConsolidationError("Acquisition deferred-tax item fields are invalid.")
        item_id = raw_item.get("item_id")
        if not isinstance(item_id, str) or item_id in seen or item_id <= previous_id:
            raise ConsolidationError("Acquisition deferred-tax items must be unique and canonically ordered.")
        seen.add(item_id)
        previous_id = item_id
        kind = raw_item.get("item_kind")
        if kind not in {"asset", "liability"}:
            raise ConsolidationError("Acquisition deferred-tax item kind is invalid.")
        fair_value = _canonical_money(raw_item.get("fair_value"), currency, f"item {item_id} fair value", non_negative=True)
        tax_basis = _canonical_money(raw_item.get("tax_basis"), currency, f"item {item_id} tax basis", non_negative=True)
        rate_raw = raw_item.get("tax_rate")
        if not isinstance(rate_raw, str):
            raise ConsolidationError("Acquisition deferred-tax tax rate must be canonical text.")
        rate = _decimal(rate_raw, f"item {item_id} tax rate", minimum=Decimal("0"), maximum=Decimal("1"))
        if _decimal_text(rate) != rate_raw:
            raise ConsolidationError("Acquisition deferred-tax tax rate is not canonical.")
        temporary = _canonical_money(raw_item.get("temporary_difference"), currency, f"item {item_id} temporary difference")
        tax_amount = _canonical_money(raw_item.get("tax_amount"), currency, f"item {item_id} tax amount")
        signed_fair = _signed(kind, fair_value.amount)
        signed_basis = _signed(kind, tax_basis.amount)
        expected_temporary = Money.from_exact(signed_fair - signed_basis, currency, strict_precision=True)
        expected_tax = Money.from_exact(expected_temporary.amount * rate, currency)
        if temporary.amount != expected_temporary.amount or tax_amount.amount != expected_tax.amount:
            raise ConsolidationError(f"Acquisition deferred-tax item {item_id} arithmetic does not reconcile.")
        expected_classification: DeferredTaxClassification = (
            "deferred_tax_liability" if expected_tax.amount > 0 else "deferred_tax_asset" if expected_tax.amount < 0 else "none"
        )
        if raw_item.get("classification") != expected_classification:
            raise ConsolidationError(f"Acquisition deferred-tax item {item_id} classification is invalid.")
        if expected_tax.amount > 0:
            liability_sum = _add(liability_sum, expected_tax.amount)
        elif expected_tax.amount < 0:
            asset_sum = _add(asset_sum, -expected_tax.amount)
    if asset_total.amount != asset_sum or liability_total.amount != liability_sum:
        raise ConsolidationError("Acquisition deferred-tax totals do not reconcile to items.")
    return dict(payload)
