"""Deterministic, non-posting ownership-change adjustment proposals.

The contract is deliberately policy-neutral: callers provide the signed
consideration effect that their approved accounting policy derives. ReconForge
only calculates the ownership/NCI delta, balances the three proposed lines,
and preserves exact input/output evidence. It does not assert statutory
accounting treatment or post to a ledger.
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

OWNERSHIP_CHANGE_SCHEMA_VERSION = 1
OWNERSHIP_CHANGE_ALGORITHM_VERSION = "ownership-change-adjustment-v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_SEMVER = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")

OwnershipChangeLineType = Literal["nci", "consideration", "parent_equity"]


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise ConsolidationError(f"{field} is invalid.")
    return value.strip()


def _semver(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SEMVER.fullmatch(value):
        raise ConsolidationError(f"{field} must be semantic versioning.")
    return value


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


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


def _date(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ConsolidationError(f"{field} must be an ISO-8601 date.")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise ConsolidationError(f"{field} must be an ISO-8601 date.") from exc


def _percentage(value: object, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0 or value > 1:
        raise ConsolidationError(f"{field} must be a finite Decimal between zero and one.")
    return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ConsolidationError("Ownership-change decimals must be finite.")
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _multiply(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = max(28, len(left.as_tuple().digits) + len(right.as_tuple().digits) + 4)
        return left * right


@dataclass(frozen=True)
class OwnershipChangeAdjustmentRequest:
    """Approved source-bound request for one ownership-change proposal."""

    change_id: str
    subsidiary_entity_code: str
    period_id: str
    effective_date: str
    reporting_currency: str
    prior_group_ownership_percentage: Decimal
    new_group_ownership_percentage: Decimal
    net_assets: Money
    consideration_effect: Money
    nci_account_code: str
    consideration_account_code: str
    parent_equity_account_code: str
    policy_id: str
    policy_version: str
    source_reference: str
    source_digest: str
    prepared_by: str
    prepared_at: str
    approved_by: str
    approved_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "change_id", _identifier(self.change_id, "Ownership change identifier"))
        object.__setattr__(self, "subsidiary_entity_code", _identifier(self.subsidiary_entity_code, "Subsidiary entity"))
        object.__setattr__(self, "period_id", _identifier(self.period_id, "Ownership change period"))
        object.__setattr__(self, "effective_date", _date(self.effective_date, "Ownership change effective date"))
        currency = self.reporting_currency.strip().upper() if isinstance(self.reporting_currency, str) else ""
        if not re.fullmatch(r"[A-Z][A-Z0-9]{2,5}", currency):
            raise ConsolidationError("Ownership-change reporting currency is invalid.")
        object.__setattr__(self, "reporting_currency", currency)
        prior = _percentage(self.prior_group_ownership_percentage, "Prior group ownership percentage")
        new = _percentage(self.new_group_ownership_percentage, "New group ownership percentage")
        object.__setattr__(self, "prior_group_ownership_percentage", prior)
        object.__setattr__(self, "new_group_ownership_percentage", new)
        for field, value in (("net_assets", self.net_assets), ("consideration_effect", self.consideration_effect)):
            if not isinstance(value, Money) or value.currency != currency:
                raise ConsolidationError(f"Ownership-change {field} must use the reporting currency.")
        for field in ("nci_account_code", "consideration_account_code", "parent_equity_account_code", "policy_id"):
            object.__setattr__(self, field, _identifier(getattr(self, field), field.replace("_", " ")))
        if len({self.nci_account_code, self.consideration_account_code, self.parent_equity_account_code}) != 3:
            raise ConsolidationError("Ownership-change adjustment accounts must be distinct.")
        object.__setattr__(self, "policy_version", _semver(self.policy_version, "Ownership-change policy version"))
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "Ownership-change source reference"))
        if not isinstance(self.source_digest, str) or not _SHA256.fullmatch(self.source_digest):
            raise ConsolidationError("Ownership-change source digest must be a lowercase SHA-256 digest.")
        object.__setattr__(self, "prepared_by", _identifier(self.prepared_by, "Ownership-change preparer"))
        object.__setattr__(self, "approved_by", _identifier(self.approved_by, "Ownership-change approver"))
        if self.prepared_by == self.approved_by:
            raise ConsolidationError("Ownership-change preparation and approval require different actors.")
        prepared_at = _timestamp(self.prepared_at, "Ownership-change preparation timestamp")
        approved_at = _timestamp(self.approved_at, "Ownership-change approval timestamp")
        if approved_at > prepared_at:
            raise ConsolidationError("Ownership-change approval must precede proposal preparation.")
        object.__setattr__(self, "prepared_at", prepared_at)
        object.__setattr__(self, "approved_at", approved_at)

    def to_dict(self) -> dict[str, object]:
        return {
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "change_id": self.change_id,
            "consideration_account_code": self.consideration_account_code,
            "consideration_effect": self.consideration_effect.to_canonical_dict(),
            "effective_date": self.effective_date,
            "nci_account_code": self.nci_account_code,
            "net_assets": self.net_assets.to_canonical_dict(),
            "new_group_ownership_percentage": _decimal_text(self.new_group_ownership_percentage),
            "parent_equity_account_code": self.parent_equity_account_code,
            "period_id": self.period_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "prepared_at": self.prepared_at,
            "prepared_by": self.prepared_by,
            "prior_group_ownership_percentage": _decimal_text(self.prior_group_ownership_percentage),
            "reporting_currency": self.reporting_currency,
            "source_digest": self.source_digest,
            "source_reference": self.source_reference,
            "subsidiary_entity_code": self.subsidiary_entity_code,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class OwnershipChangeAdjustmentLine:
    account_code: str
    line_type: OwnershipChangeLineType
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
class OwnershipChangeAdjustmentResult:
    schema_version: int
    algorithm_version: str
    request_digest: str
    result_digest: str
    change_id: str
    reporting_currency: str
    prior_nci_percentage: Decimal
    new_nci_percentage: Decimal
    unrounded_nci_effect: Decimal
    nci_rounding_delta: Decimal
    lines: tuple[OwnershipChangeAdjustmentLine, ...]
    posted: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "change_id": self.change_id,
            "lines": [line.to_dict() for line in self.lines],
            "new_nci_percentage": _decimal_text(self.new_nci_percentage),
            "nci_rounding_delta": _decimal_text(self.nci_rounding_delta),
            "posted": self.posted,
            "prior_nci_percentage": _decimal_text(self.prior_nci_percentage),
            "reporting_currency": self.reporting_currency,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "schema_version": self.schema_version,
            "unrounded_nci_effect": _decimal_text(self.unrounded_nci_effect),
        }


def prepare_ownership_change_adjustment(
    request: OwnershipChangeAdjustmentRequest,
) -> OwnershipChangeAdjustmentResult:
    """Return a balanced, explainable, non-posting ownership-change proposal."""

    if not isinstance(request, OwnershipChangeAdjustmentRequest):
        raise ConsolidationError("An ownership-change adjustment request is required.")
    currency = request.reporting_currency
    prior_nci = Decimal("1") - request.prior_group_ownership_percentage
    new_nci = Decimal("1") - request.new_group_ownership_percentage
    unrounded_nci_effect = _multiply(request.net_assets.amount, new_nci - prior_nci)
    nci_effect = Money.from_exact(unrounded_nci_effect, currency)
    nci_rounding_delta = nci_effect.amount - unrounded_nci_effect
    parent_equity_effect = -(nci_effect.amount + request.consideration_effect.amount)
    parent_equity = Money.from_exact(parent_equity_effect, currency, strict_precision=True)
    lines = (
        OwnershipChangeAdjustmentLine(request.nci_account_code, "nci", nci_effect, request.source_reference),
        OwnershipChangeAdjustmentLine(
            request.consideration_account_code,
            "consideration",
            request.consideration_effect,
            request.source_reference,
        ),
        OwnershipChangeAdjustmentLine(
            request.parent_equity_account_code,
            "parent_equity",
            parent_equity,
            request.source_reference,
        ),
    )
    payload = {
        "algorithm_version": OWNERSHIP_CHANGE_ALGORITHM_VERSION,
        "change_id": request.change_id,
        "lines": [line.to_dict() for line in lines],
        "new_nci_percentage": _decimal_text(new_nci),
        "nci_rounding_delta": _decimal_text(nci_rounding_delta),
        "posted": False,
        "prior_nci_percentage": _decimal_text(prior_nci),
        "reporting_currency": currency,
        "request_digest": request.digest,
        "schema_version": OWNERSHIP_CHANGE_SCHEMA_VERSION,
        "unrounded_nci_effect": _decimal_text(unrounded_nci_effect),
    }
    return OwnershipChangeAdjustmentResult(
        schema_version=OWNERSHIP_CHANGE_SCHEMA_VERSION,
        algorithm_version=OWNERSHIP_CHANGE_ALGORITHM_VERSION,
        request_digest=request.digest,
        result_digest=_digest(payload),
        change_id=request.change_id,
        reporting_currency=currency,
        prior_nci_percentage=prior_nci,
        new_nci_percentage=new_nci,
        unrounded_nci_effect=unrounded_nci_effect,
        nci_rounding_delta=nci_rounding_delta,
        lines=lines,
    )


def verify_ownership_change_adjustment_payload(payload: object) -> dict[str, object]:
    """Verify a serialized result's digest and balanced Decimal line effects."""

    if not isinstance(payload, dict):
        raise ConsolidationError("Ownership-change adjustment payload must be an object.")
    expected_digest = payload.get("result_digest")
    if not isinstance(expected_digest, str):
        raise ConsolidationError("Ownership-change adjustment result digest is missing.")
    unsigned = dict(payload)
    unsigned.pop("result_digest", None)
    if _digest(unsigned) != expected_digest:
        raise ConsolidationError("Ownership-change adjustment result digest mismatch.")
    lines = payload.get("lines")
    if not isinstance(lines, list) or len(lines) != 3:
        raise ConsolidationError("Ownership-change adjustment requires exactly three lines.")
    total = Decimal("0")
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("amount"), dict):
            raise ConsolidationError("Ownership-change adjustment line is invalid.")
        amount = line["amount"].get("amount")
        if not isinstance(amount, str):
            raise ConsolidationError("Ownership-change adjustment amount is invalid.")
        total += Decimal(amount)
    if total != 0:
        raise ConsolidationError("Ownership-change adjustment lines must balance exactly.")
    return dict(payload)


__all__ = [
    "OWNERSHIP_CHANGE_ALGORITHM_VERSION",
    "OWNERSHIP_CHANGE_SCHEMA_VERSION",
    "OwnershipChangeAdjustmentLine",
    "OwnershipChangeAdjustmentRequest",
    "OwnershipChangeAdjustmentResult",
    "prepare_ownership_change_adjustment",
    "verify_ownership_change_adjustment_payload",
]
