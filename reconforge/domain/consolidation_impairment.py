"""Deterministic, non-posting impairment test bridge.

The bridge makes a bounded impairment calculation reproducible without
pretending to decide a statutory valuation, cash-generating-unit boundary,
discount rate, or journal posting.  Operators provide the carrying and
recoverable amounts they have approved; ReconForge only calculates the
visible loss/headroom and preserves the source and maker-checker lineage.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Literal

from reconforge.domain.consolidation import ConsolidationError
from reconforge.utils.money import Money, parse_exact_amount

CONSOLIDATION_IMPAIRMENT_SCHEMA_VERSION = 1
CONSOLIDATION_IMPAIRMENT_ALGORITHM_VERSION = "consolidation-impairment-bridge-v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_SEMVER = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")

ImpairmentUnitKind = Literal["goodwill", "asset"]
ImpairmentStatus = Literal["impaired", "not_impaired"]


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise ConsolidationError(f"{field} is invalid.")
    return value.strip()


def _semver(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SEMVER.fullmatch(value):
        raise ConsolidationError(f"{field} must be semantic versioning.")
    return value


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


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ConsolidationError("Impairment decimals must be finite.")
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise ConsolidationError(f"{field} must use an exact decimal value.")
    try:
        parsed = parse_exact_amount(value)
    except (TypeError, ValueError) as exc:
        raise ConsolidationError(f"{field} must use an exact decimal value.") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ConsolidationError(f"{field} must be finite and non-negative.")
    return parsed


def _money(value: object, currency: str, field: str) -> Money:
    if not isinstance(value, Money) or value.currency != currency or not value.amount.is_finite() or value.amount < 0:
        raise ConsolidationError(f"Impairment {field} must be finite, non-negative Money in the reporting currency.")
    return value


def _sum(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext() as context:
        context.prec = max(28, sum(len(value.as_tuple().digits) for value in values) + 4)
        return sum(values, Decimal("0"))


@dataclass(frozen=True)
class ConsolidationImpairmentUnit:
    """One source-bound carrying/recoverable amount pair."""

    unit_id: str
    unit_kind: ImpairmentUnitKind
    account_code: str
    carrying_amount: Money
    recoverable_amount: Money
    source_reference: str
    source_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "unit_id", _identifier(self.unit_id, "Impairment unit"))
        if self.unit_kind not in {"goodwill", "asset"}:
            raise ConsolidationError("Impairment unit kind must be goodwill or asset.")
        object.__setattr__(self, "account_code", _identifier(self.account_code, "Impairment account"))
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "Impairment source reference"))
        if not isinstance(self.source_digest, str) or not _SHA256.fullmatch(self.source_digest):
            raise ConsolidationError("Impairment source digest must be a lowercase SHA-256 digest.")
        if not isinstance(self.carrying_amount, Money) or not isinstance(self.recoverable_amount, Money):
            raise ConsolidationError("Impairment amounts must be Money.")
        if self.carrying_amount.currency != self.recoverable_amount.currency:
            raise ConsolidationError("Impairment carrying and recoverable amounts must use one currency.")
        if self.carrying_amount.amount < 0 or self.recoverable_amount.amount < 0:
            raise ConsolidationError("Impairment amounts must be non-negative.")

    def impairment_loss(self, currency: str) -> Money:
        _money(self.carrying_amount, currency, "carrying amount")
        _money(self.recoverable_amount, currency, "recoverable amount")
        loss = max(self.carrying_amount.amount - self.recoverable_amount.amount, Decimal("0"))
        return Money.from_exact(loss, currency, strict_precision=True)

    def recoverable_headroom(self, currency: str) -> Money:
        _money(self.carrying_amount, currency, "carrying amount")
        _money(self.recoverable_amount, currency, "recoverable amount")
        headroom = max(self.recoverable_amount.amount - self.carrying_amount.amount, Decimal("0"))
        return Money.from_exact(headroom, currency, strict_precision=True)

    def status(self, currency: str) -> ImpairmentStatus:
        return "impaired" if self.impairment_loss(currency).amount > 0 else "not_impaired"

    def to_input_dict(self) -> dict[str, object]:
        return {
            "account_code": self.account_code,
            "carrying_amount": self.carrying_amount.to_canonical_dict(),
            "recoverable_amount": self.recoverable_amount.to_canonical_dict(),
            "source_digest": self.source_digest,
            "source_reference": self.source_reference,
            "unit_id": self.unit_id,
            "unit_kind": self.unit_kind,
        }

    def to_dict(self, *, currency: str) -> dict[str, object]:
        return {
            **self.to_input_dict(),
            "impairment_loss": self.impairment_loss(currency).to_canonical_dict(),
            "recoverable_headroom": self.recoverable_headroom(currency).to_canonical_dict(),
            "status": self.status(currency),
        }


@dataclass(frozen=True)
class ConsolidationImpairmentBridgeRequest:
    """Approved inputs for a bounded, non-posting impairment artifact."""

    impairment_test_id: str
    entity_code: str
    period_id: str
    reporting_currency: str
    units: tuple[ConsolidationImpairmentUnit, ...]
    policy_id: str
    policy_version: str
    source_reference: str
    source_digest: str
    prepared_by: str
    prepared_at: str
    approved_by: str
    approved_at: str

    def __post_init__(self) -> None:
        for field in ("impairment_test_id", "entity_code", "period_id"):
            object.__setattr__(self, field, _identifier(getattr(self, field), field.replace("_", " ")))
        currency = self.reporting_currency.strip().upper() if isinstance(self.reporting_currency, str) else ""
        if not _IDENTIFIER.fullmatch(currency) or len(currency) < 3 or len(currency) > 6:
            raise ConsolidationError("Impairment reporting currency is invalid.")
        object.__setattr__(self, "reporting_currency", currency)
        if not isinstance(self.units, tuple) or not self.units or len(self.units) > 4096:
            raise ConsolidationError("Impairment requires between one and 4096 units.")
        unit_ids: set[str] = set()
        for unit in self.units:
            if not isinstance(unit, ConsolidationImpairmentUnit):
                raise ConsolidationError("Impairment units must use the typed unit contract.")
            if unit.unit_id in unit_ids:
                raise ConsolidationError("Impairment unit IDs must be unique.")
            unit_ids.add(unit.unit_id)
            _money(unit.carrying_amount, currency, f"unit {unit.unit_id} carrying amount")
            _money(unit.recoverable_amount, currency, f"unit {unit.unit_id} recoverable amount")
        object.__setattr__(self, "units", tuple(sorted(self.units, key=lambda item: item.unit_id)))
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "Impairment policy"))
        object.__setattr__(self, "policy_version", _semver(self.policy_version, "Impairment policy version"))
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "Impairment source reference"))
        if not isinstance(self.source_digest, str) or not _SHA256.fullmatch(self.source_digest):
            raise ConsolidationError("Impairment source digest must be a lowercase SHA-256 digest.")
        object.__setattr__(self, "prepared_by", _identifier(self.prepared_by, "Impairment preparer"))
        object.__setattr__(self, "approved_by", _identifier(self.approved_by, "Impairment approver"))
        if self.prepared_by == self.approved_by:
            raise ConsolidationError("Impairment preparation and approval require different actors.")
        prepared_at = _timestamp(self.prepared_at, "Impairment preparation timestamp")
        approved_at = _timestamp(self.approved_at, "Impairment approval timestamp")
        if approved_at > prepared_at:
            raise ConsolidationError("Impairment approval must precede preparation.")
        object.__setattr__(self, "prepared_at", prepared_at)
        object.__setattr__(self, "approved_at", approved_at)

    def to_dict(self) -> dict[str, object]:
        return {
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "entity_code": self.entity_code,
            "impairment_test_id": self.impairment_test_id,
            "period_id": self.period_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "prepared_at": self.prepared_at,
            "prepared_by": self.prepared_by,
            "reporting_currency": self.reporting_currency,
            "source_digest": self.source_digest,
            "source_reference": self.source_reference,
            "units": [unit.to_input_dict() for unit in self.units],
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class ConsolidationImpairmentBridgeResult:
    schema_version: int
    algorithm_version: str
    request_digest: str
    result_digest: str
    impairment_test_id: str
    reporting_currency: str
    total_carrying_amount: Money
    total_recoverable_amount: Money
    total_impairment_loss: Money
    units: tuple[ConsolidationImpairmentUnit, ...]
    posted: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "impairment_test_id": self.impairment_test_id,
            "posted": self.posted,
            "reporting_currency": self.reporting_currency,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "schema_version": self.schema_version,
            "total_carrying_amount": self.total_carrying_amount.to_canonical_dict(),
            "total_impairment_loss": self.total_impairment_loss.to_canonical_dict(),
            "total_recoverable_amount": self.total_recoverable_amount.to_canonical_dict(),
            "units": [unit.to_dict(currency=self.reporting_currency) for unit in self.units],
        }


def prepare_consolidation_impairment_bridge(
    request: ConsolidationImpairmentBridgeRequest,
) -> ConsolidationImpairmentBridgeResult:
    """Calculate visible impairment loss/headroom without posting or valuation policy."""

    if not isinstance(request, ConsolidationImpairmentBridgeRequest):
        raise ConsolidationError("A consolidation impairment bridge request is required.")
    currency = request.reporting_currency
    carrying = Money.from_exact(_sum(tuple(unit.carrying_amount.amount for unit in request.units)), currency, strict_precision=True)
    recoverable = Money.from_exact(_sum(tuple(unit.recoverable_amount.amount for unit in request.units)), currency, strict_precision=True)
    loss = Money.from_exact(_sum(tuple(unit.impairment_loss(currency).amount for unit in request.units)), currency, strict_precision=True)
    unsigned: dict[str, object] = {
        "algorithm_version": CONSOLIDATION_IMPAIRMENT_ALGORITHM_VERSION,
        "impairment_test_id": request.impairment_test_id,
        "posted": False,
        "reporting_currency": currency,
        "request_digest": request.digest,
        "schema_version": CONSOLIDATION_IMPAIRMENT_SCHEMA_VERSION,
        "total_carrying_amount": carrying.to_canonical_dict(),
        "total_impairment_loss": loss.to_canonical_dict(),
        "total_recoverable_amount": recoverable.to_canonical_dict(),
        "units": [unit.to_dict(currency=currency) for unit in request.units],
    }
    return ConsolidationImpairmentBridgeResult(
        schema_version=CONSOLIDATION_IMPAIRMENT_SCHEMA_VERSION,
        algorithm_version=CONSOLIDATION_IMPAIRMENT_ALGORITHM_VERSION,
        request_digest=request.digest,
        result_digest=_digest(unsigned),
        impairment_test_id=request.impairment_test_id,
        reporting_currency=currency,
        total_carrying_amount=carrying,
        total_recoverable_amount=recoverable,
        total_impairment_loss=loss,
        units=request.units,
    )


def _canonical_money(value: object, currency: str, field: str) -> Money:
    try:
        result = Money.from_canonical_dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, KeyError) as exc:
        raise ConsolidationError(f"Impairment {field} money is invalid.") from exc
    return _money(result, currency, field)


def verify_consolidation_impairment_bridge_payload(payload: object) -> dict[str, object]:
    """Recompute the bounded artifact and reject any arithmetic or digest tampering."""

    if not isinstance(payload, dict):
        raise ConsolidationError("Consolidation impairment payload must be an object.")
    supplied_digest = payload.get("result_digest")
    if not isinstance(supplied_digest, str) or not _SHA256.fullmatch(supplied_digest):
        raise ConsolidationError("Consolidation impairment result digest is invalid.")
    if payload.get("schema_version") != CONSOLIDATION_IMPAIRMENT_SCHEMA_VERSION or payload.get("algorithm_version") != CONSOLIDATION_IMPAIRMENT_ALGORITHM_VERSION:
        raise ConsolidationError("Consolidation impairment schema is unsupported.")
    expected_keys = {
        "algorithm_version", "impairment_test_id", "posted", "reporting_currency", "request_digest", "result_digest",
        "schema_version", "total_carrying_amount", "total_impairment_loss", "total_recoverable_amount", "units",
    }
    if set(payload) != expected_keys or payload.get("posted") is not False:
        raise ConsolidationError("Consolidation impairment payload fields are not exactly declared.")
    currency = payload.get("reporting_currency")
    if not isinstance(currency, str):
        raise ConsolidationError("Consolidation impairment reporting currency is invalid.")
    raw_units = payload.get("units")
    if not isinstance(raw_units, list):
        raise ConsolidationError("Consolidation impairment units are invalid.")
    units: list[ConsolidationImpairmentUnit] = []
    expected_unit_keys = {
        "account_code", "carrying_amount", "recoverable_amount", "source_digest", "source_reference", "unit_id", "unit_kind",
        "impairment_loss", "recoverable_headroom", "status",
    }
    for raw in raw_units:
        if not isinstance(raw, dict) or set(raw) != expected_unit_keys:
            raise ConsolidationError("Consolidation impairment unit fields are not exactly declared.")
        units.append(
            ConsolidationImpairmentUnit(
                unit_id=raw["unit_id"],
                unit_kind=raw["unit_kind"],
                account_code=raw["account_code"],
                carrying_amount=_canonical_money(raw["carrying_amount"], currency, "carrying amount"),
                recoverable_amount=_canonical_money(raw["recoverable_amount"], currency, "recoverable amount"),
                source_reference=raw["source_reference"],
                source_digest=raw["source_digest"],
            )
        )
    # The request is not embedded in the result, so verify its derived unit arithmetic and
    # canonical ordering directly, then verify the result digest over the supplied artifact.
    if tuple(unit.unit_id for unit in units) != tuple(sorted(unit.unit_id for unit in units)):
        raise ConsolidationError("Consolidation impairment units are not canonically ordered.")
    expected_units = [unit.to_dict(currency=currency) for unit in units]
    if expected_units != raw_units:
        raise ConsolidationError("Consolidation impairment unit arithmetic does not reproduce.")
    carrying = Money.from_exact(_sum(tuple(unit.carrying_amount.amount for unit in units)), currency, strict_precision=True)
    recoverable = Money.from_exact(_sum(tuple(unit.recoverable_amount.amount for unit in units)), currency, strict_precision=True)
    loss = Money.from_exact(_sum(tuple(unit.impairment_loss(currency).amount for unit in units)), currency, strict_precision=True)
    unsigned = dict(payload)
    unsigned.pop("result_digest")
    if unsigned["total_carrying_amount"] != carrying.to_canonical_dict() or unsigned["total_recoverable_amount"] != recoverable.to_canonical_dict() or unsigned["total_impairment_loss"] != loss.to_canonical_dict():
        raise ConsolidationError("Consolidation impairment totals do not reproduce.")
    if supplied_digest != _digest(unsigned):
        raise ConsolidationError("Consolidation impairment result digest mismatch.")
    return payload


__all__ = [
    "CONSOLIDATION_IMPAIRMENT_ALGORITHM_VERSION",
    "CONSOLIDATION_IMPAIRMENT_SCHEMA_VERSION",
    "ConsolidationImpairmentBridgeRequest",
    "ConsolidationImpairmentBridgeResult",
    "ConsolidationImpairmentUnit",
    "prepare_consolidation_impairment_bridge",
    "verify_consolidation_impairment_bridge_payload",
]
