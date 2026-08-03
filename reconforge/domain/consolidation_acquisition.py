"""Deterministic, non-posting acquisition fair-value/goodwill bridge.

This module deliberately stops at an approved, source-bound calculation
artifact. It does not decide statutory acquisition accounting, tax, purchase
price allocation detail, or post a journal. The bridge makes the arithmetic
and the policy decision visible so a qualified reviewer can decide what to do
next without a hidden balancing line.
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
from reconforge.utils.money import Money

ACQUISITION_BRIDGE_SCHEMA_VERSION = 1
ACQUISITION_BRIDGE_ALGORITHM_VERSION = "acquisition-fair-value-goodwill-bridge-v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_SEMVER = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")

AcquisitionBridgeLineType = Literal[
    "consideration",
    "nci",
    "identifiable_net_assets",
    "goodwill",
    "bargain_purchase",
]


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


def _money(value: object, currency: str, field: str) -> Money:
    if not isinstance(value, Money) or value.currency != currency or not value.amount.is_finite():
        raise ConsolidationError(f"Acquisition {field} must use the reporting currency and be finite.")
    if value.amount < 0:
        raise ConsolidationError(f"Acquisition {field} must not be negative.")
    return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ConsolidationError("Acquisition bridge decimals must be finite.")
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _add(*values: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = max(28, sum(len(value.as_tuple().digits) for value in values) + 4)
        return sum(values, Decimal("0"))


@dataclass(frozen=True)
class AcquisitionFairValueBridgeRequest:
    """Approved source-bound inputs for one non-posting acquisition bridge."""

    acquisition_id: str
    subsidiary_entity_code: str
    period_id: str
    acquisition_date: str
    reporting_currency: str
    consideration: Money
    nci_fair_value: Money
    identifiable_net_assets_fair_value: Money
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
            raise ConsolidationError("Acquisition reporting currency is invalid.")
        object.__setattr__(self, "reporting_currency", currency)
        if not isinstance(self.allow_bargain_purchase, bool):
            raise ConsolidationError("Acquisition bargain-purchase policy must be boolean.")
        for field in ("consideration", "nci_fair_value", "identifiable_net_assets_fair_value"):
            object.__setattr__(self, field, _money(getattr(self, field), currency, field))
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
            raise ConsolidationError("Acquisition bridge accounts must be distinct.")
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "Acquisition policy"))
        object.__setattr__(self, "policy_version", _semver(self.policy_version, "Acquisition policy version"))
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "Acquisition source reference"))
        if not isinstance(self.source_digest, str) or not _SHA256.fullmatch(self.source_digest):
            raise ConsolidationError("Acquisition source digest must be a lowercase SHA-256 digest.")
        object.__setattr__(self, "prepared_by", _identifier(self.prepared_by, "Acquisition preparer"))
        object.__setattr__(self, "approved_by", _identifier(self.approved_by, "Acquisition approver"))
        if self.prepared_by == self.approved_by:
            raise ConsolidationError("Acquisition preparation and approval require different actors.")
        prepared_at = _timestamp(self.prepared_at, "Acquisition preparation timestamp")
        approved_at = _timestamp(self.approved_at, "Acquisition approval timestamp")
        if approved_at > prepared_at:
            raise ConsolidationError("Acquisition approval must precede proposal preparation.")
        object.__setattr__(self, "prepared_at", prepared_at)
        object.__setattr__(self, "approved_at", approved_at)

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
            "identifiable_net_assets_fair_value": self.identifiable_net_assets_fair_value.to_canonical_dict(),
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
class AcquisitionFairValueBridgeLine:
    account_code: str
    line_type: AcquisitionBridgeLineType
    amount: Money
    source_reference: str

    def to_dict(self) -> dict[str, object]:
        return {
            "account_code": self.account_code,
            "amount": self.amount.to_canonical_dict(),
            "line_type": self.line_type,
            "source_reference": self.source_reference,
        }


@dataclass(frozen=True)
class AcquisitionFairValueBridgeResult:
    schema_version: int
    algorithm_version: str
    request_digest: str
    result_digest: str
    acquisition_id: str
    reporting_currency: str
    goodwill: Money
    bargain_purchase: Money
    lines: tuple[AcquisitionFairValueBridgeLine, ...]
    posted: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "acquisition_id": self.acquisition_id,
            "algorithm_version": self.algorithm_version,
            "bargain_purchase": self.bargain_purchase.to_canonical_dict(),
            "goodwill": self.goodwill.to_canonical_dict(),
            "lines": [line.to_dict() for line in self.lines],
            "posted": self.posted,
            "reporting_currency": self.reporting_currency,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "schema_version": self.schema_version,
        }


def prepare_acquisition_fair_value_bridge(
    request: AcquisitionFairValueBridgeRequest,
) -> AcquisitionFairValueBridgeResult:
    """Build a balanced, explainable, non-posting acquisition bridge."""

    if not isinstance(request, AcquisitionFairValueBridgeRequest):
        raise ConsolidationError("An acquisition fair-value bridge request is required.")
    currency = request.reporting_currency
    bridge_delta = _add(
        request.consideration.amount,
        request.nci_fair_value.amount,
        -request.identifiable_net_assets_fair_value.amount,
    )
    if bridge_delta < 0 and not request.allow_bargain_purchase:
        raise ConsolidationError("Acquisition bridge produces a bargain purchase but policy forbids it.")
    goodwill_amount = max(bridge_delta, Decimal("0"))
    bargain_amount = max(-bridge_delta, Decimal("0"))
    goodwill = Money.from_exact(goodwill_amount, currency, strict_precision=True)
    bargain = Money.from_exact(bargain_amount, currency, strict_precision=True)
    lines: list[AcquisitionFairValueBridgeLine] = [
        AcquisitionFairValueBridgeLine(
            request.consideration_account_code,
            "consideration",
            request.consideration,
            request.source_reference,
        ),
        AcquisitionFairValueBridgeLine(
            request.nci_account_code,
            "nci",
            request.nci_fair_value,
            request.source_reference,
        ),
        AcquisitionFairValueBridgeLine(
            request.identifiable_net_assets_account_code,
            "identifiable_net_assets",
            Money.from_exact(-request.identifiable_net_assets_fair_value.amount, currency, strict_precision=True),
            request.source_reference,
        ),
    ]
    if goodwill_amount:
        lines.append(
            AcquisitionFairValueBridgeLine(
                request.goodwill_account_code,
                "goodwill",
                Money.from_exact(-goodwill_amount, currency, strict_precision=True),
                request.source_reference,
            )
        )
    if bargain_amount:
        lines.append(
            AcquisitionFairValueBridgeLine(
                request.bargain_purchase_account_code,
                "bargain_purchase",
                bargain,
                request.source_reference,
            )
        )
    payload = {
        "acquisition_id": request.acquisition_id,
        "algorithm_version": ACQUISITION_BRIDGE_ALGORITHM_VERSION,
        "bargain_purchase": bargain.to_canonical_dict(),
        "goodwill": goodwill.to_canonical_dict(),
        "lines": [line.to_dict() for line in lines],
        "posted": False,
        "reporting_currency": currency,
        "request_digest": request.digest,
        "schema_version": ACQUISITION_BRIDGE_SCHEMA_VERSION,
    }
    return AcquisitionFairValueBridgeResult(
        schema_version=ACQUISITION_BRIDGE_SCHEMA_VERSION,
        algorithm_version=ACQUISITION_BRIDGE_ALGORITHM_VERSION,
        request_digest=request.digest,
        result_digest=_digest(payload),
        acquisition_id=request.acquisition_id,
        reporting_currency=currency,
        goodwill=goodwill,
        bargain_purchase=bargain,
        lines=tuple(lines),
    )


def verify_acquisition_fair_value_bridge_payload(payload: object) -> dict[str, object]:
    """Verify result digest, currency consistency, and exact bridge balance."""

    if not isinstance(payload, dict):
        raise ConsolidationError("Acquisition bridge payload must be an object.")
    expected_digest = payload.get("result_digest")
    if not isinstance(expected_digest, str):
        raise ConsolidationError("Acquisition bridge result digest is missing.")
    unsigned = dict(payload)
    unsigned.pop("result_digest", None)
    if _digest(unsigned) != expected_digest:
        raise ConsolidationError("Acquisition bridge result digest mismatch.")
    if payload.get("posted") is not False:
        raise ConsolidationError("Acquisition bridge cannot be posted.")
    currency = payload.get("reporting_currency")
    if not isinstance(currency, str):
        raise ConsolidationError("Acquisition bridge reporting currency is missing.")
    lines = payload.get("lines")
    if not isinstance(lines, list) or len(lines) not in {4, 5}:
        raise ConsolidationError("Acquisition bridge requires four or five lines.")
    seen: set[str] = set()
    total = Decimal("0")
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("line_type"), str):
            raise ConsolidationError("Acquisition bridge line is invalid.")
        line_type = line["line_type"]
        if line_type in seen or line_type not in {
            "consideration",
            "nci",
            "identifiable_net_assets",
            "goodwill",
            "bargain_purchase",
        }:
            raise ConsolidationError("Acquisition bridge line types must be unique and known.")
        seen.add(line_type)
        amount = line.get("amount")
        if not isinstance(amount, dict) or amount.get("currency") != currency or not isinstance(amount.get("amount"), str):
            raise ConsolidationError("Acquisition bridge line amount is invalid.")
        total += Decimal(amount["amount"])
    if {"consideration", "nci", "identifiable_net_assets"} - seen:
        raise ConsolidationError("Acquisition bridge core lines are missing.")
    if "goodwill" in seen and "bargain_purchase" in seen:
        raise ConsolidationError("Acquisition bridge cannot contain goodwill and bargain purchase together.")
    if total != 0:
        raise ConsolidationError("Acquisition bridge lines must balance exactly.")
    return dict(payload)


__all__ = [
    "ACQUISITION_BRIDGE_ALGORITHM_VERSION",
    "ACQUISITION_BRIDGE_SCHEMA_VERSION",
    "AcquisitionBridgeLineType",
    "AcquisitionFairValueBridgeLine",
    "AcquisitionFairValueBridgeRequest",
    "AcquisitionFairValueBridgeResult",
    "prepare_acquisition_fair_value_bridge",
    "verify_acquisition_fair_value_bridge_payload",
]
