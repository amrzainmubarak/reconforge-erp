"""Deterministic ownership, NCI, elimination, and worksheet invariants."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from typing import Literal, cast

from reconforge.domain.consolidation import (
    ConsolidationAccountType,
    ConsolidationError,
    ConsolidationTranslationResult,
    verify_consolidation_result_payload,
)
from reconforge.utils.money import InvalidAmountError, Money

CONSOLIDATION_WORKSHEET_SCHEMA_VERSION = 1
CONSOLIDATION_WORKSHEET_ALGORITHM_VERSION = "consolidation-worksheet-v1"
MAX_OWNERSHIP_INTERESTS = 10_000
MAX_CONSOLIDATION_ELIMINATIONS = 20_000
MAX_CONSOLIDATION_ELIMINATION_LINES = 100_000

ConsolidationEliminationType = Literal[
    "intercompany_balance",
    "intercompany_transaction",
    "investment_equity",
    "other",
]

_ACCOUNT_TYPES = frozenset({"Asset", "Liability", "Equity", "Income", "Expense"})
_ELIMINATION_TYPES = frozenset(
    {"intercompany_balance", "intercompany_transaction", "investment_equity", "other"}
)
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_SEMVER_PATTERN = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ConsolidationError(f"{field} is invalid.")
    clean = value.strip()
    if not _IDENTIFIER_PATTERN.fullmatch(clean):
        raise ConsolidationError(f"{field} is invalid.")
    return clean


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ConsolidationError(f"{field} must be a lowercase SHA-256 digest.")
    return value


def _semver(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SEMVER_PATTERN.fullmatch(value):
        raise ConsolidationError(f"{field} must be an exact semantic version.")
    return value


def _bounded_text(value: object, field: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str):
        raise ConsolidationError(f"{field} is invalid.")
    clean = value.strip()
    if not clean or len(clean) > maximum or any(ord(character) < 32 for character in clean):
        raise ConsolidationError(f"{field} is invalid.")
    return clean


def _iso_date(value: object, field: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ConsolidationError(f"{field} must be an ISO-8601 date.")
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ConsolidationError(f"{field} must be an ISO-8601 date.") from exc
    return parsed.isoformat()


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConsolidationError(f"{field} must be a timezone-aware ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConsolidationError(f"{field} must be a timezone-aware ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConsolidationError(f"{field} must be a timezone-aware ISO-8601 timestamp.")
    if parsed.microsecond:
        raise ConsolidationError(f"{field} must use whole-second precision.")
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ConsolidationError(f"{field} must be a finite Decimal.")
    return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ConsolidationError("Consolidation decimal values must be finite.")
    if value == 0:
        return "0"
    sign, raw_digits, raw_exponent = value.as_tuple()
    exponent = int(raw_exponent)
    digits = list(raw_digits)
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    digit_text = "".join(str(digit) for digit in digits)
    if exponent >= 0:
        text = digit_text + ("0" * exponent)
    else:
        point = len(digit_text) + exponent
        text = f"{digit_text[:point]}.{digit_text[point:]}" if point > 0 else f"0.{('0' * -point)}{digit_text}"
    return f"-{text}" if sign else text


def _decimal_from_text(value: object, field: str) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL_PATTERN.fullmatch(value):
        raise ConsolidationError(f"{field} must be canonical exact decimal text.")
    parsed = Decimal(value)
    if not parsed.is_finite() or _decimal_text(parsed) != value:
        raise ConsolidationError(f"{field} must be canonical exact decimal text.")
    return parsed


def _exact_sum(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        return Decimal("0")
    max_adjusted = max((value.adjusted() for value in values if value), default=0)
    min_exponent = min((int(value.as_tuple().exponent) for value in values), default=0)
    required_precision = max(28, max_adjusted - min_exponent + len(str(len(values))) + 4)
    with localcontext() as context:
        context.prec = required_precision
        return sum(values, Decimal("0"))


def _exact_multiply(left: Decimal, right: Decimal) -> Decimal:
    required_precision = max(28, len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2)
    with localcontext() as context:
        context.prec = required_precision
        return left * right


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _account_type(value: object) -> ConsolidationAccountType:
    if value not in _ACCOUNT_TYPES:
        raise ConsolidationError("Consolidation account type is not supported.")
    return cast(ConsolidationAccountType, value)


def _elimination_type(value: object) -> ConsolidationEliminationType:
    if value not in _ELIMINATION_TYPES:
        raise ConsolidationError("Consolidation elimination type is not supported.")
    return cast(ConsolidationEliminationType, value)


def _money_sum(values: tuple[Money, ...], currency: str) -> Money:
    for value in values:
        if value.currency != currency:
            raise ConsolidationError("Consolidation monetary values must use the reporting currency.")
    return Money.from_exact(
        _exact_sum(tuple(value.amount for value in values)),
        currency,
        strict_precision=True,
    )


@dataclass(frozen=True)
class ConsolidationLifecyclePolicy:
    """Versioned group policy for one non-posting worksheet."""

    policy_id: str
    version: str
    parent_entity_code: str
    nci_net_assets_presentation_account_code: str
    nci_profit_presentation_account_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "Consolidation lifecycle policy"))
        object.__setattr__(self, "version", _semver(self.version, "Consolidation lifecycle policy version"))
        object.__setattr__(
            self,
            "parent_entity_code",
            _identifier(self.parent_entity_code, "Consolidation parent entity"),
        )
        object.__setattr__(
            self,
            "nci_net_assets_presentation_account_code",
            _identifier(
                self.nci_net_assets_presentation_account_code,
                "NCI net-assets presentation account",
            ),
        )
        object.__setattr__(
            self,
            "nci_profit_presentation_account_code",
            _identifier(self.nci_profit_presentation_account_code, "NCI profit presentation account"),
        )
        if self.nci_net_assets_presentation_account_code == self.nci_profit_presentation_account_code:
            raise ConsolidationError("NCI presentation accounts must be distinct.")

    def to_dict(self) -> dict[str, object]:
        return {
            "nci_net_assets_presentation_account_code": self.nci_net_assets_presentation_account_code,
            "nci_profit_presentation_account_code": self.nci_profit_presentation_account_code,
            "parent_entity_code": self.parent_entity_code,
            "policy_id": self.policy_id,
            "version": self.version,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class ConsolidationOwnershipInterest:
    """One approved, effective-dated direct controlling interest."""

    interest_id: str
    parent_entity_code: str
    subsidiary_entity_code: str
    direct_ownership_percentage: Decimal
    effective_from: str
    effective_to: str
    version: str
    source_digest: str
    prepared_by: str
    approved_by: str
    approved_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "interest_id", _identifier(self.interest_id, "Ownership interest identifier"))
        object.__setattr__(
            self,
            "parent_entity_code",
            _identifier(self.parent_entity_code, "Ownership parent entity"),
        )
        object.__setattr__(
            self,
            "subsidiary_entity_code",
            _identifier(self.subsidiary_entity_code, "Ownership subsidiary entity"),
        )
        if self.parent_entity_code == self.subsidiary_entity_code:
            raise ConsolidationError("Ownership parent and subsidiary must be different entities.")
        percentage = _decimal(self.direct_ownership_percentage, "Direct ownership percentage")
        if percentage <= 0 or percentage > 1:
            raise ConsolidationError("Direct ownership percentage must be greater than zero and at most one.")
        object.__setattr__(self, "direct_ownership_percentage", percentage)
        effective_from = _iso_date(self.effective_from, "Ownership effective-from date")
        effective_to = _iso_date(self.effective_to, "Ownership effective-to date", optional=True)
        if effective_to and effective_from > effective_to:
            raise ConsolidationError("Ownership effective-from date must not follow effective-to date.")
        object.__setattr__(self, "effective_from", effective_from)
        object.__setattr__(self, "effective_to", effective_to)
        object.__setattr__(self, "version", _semver(self.version, "Ownership interest version"))
        object.__setattr__(self, "source_digest", _sha256(self.source_digest, "Ownership source digest"))
        object.__setattr__(self, "prepared_by", _identifier(self.prepared_by, "Ownership preparer"))
        object.__setattr__(self, "approved_by", _identifier(self.approved_by, "Ownership approver"))
        if self.prepared_by == self.approved_by:
            raise ConsolidationError("Ownership preparation and approval require different human actors.")
        object.__setattr__(self, "approved_at", _timestamp(self.approved_at, "Ownership approval timestamp"))

    def is_effective(self, reporting_date: str) -> bool:
        return self.effective_from <= reporting_date and (
            not self.effective_to or reporting_date <= self.effective_to
        )

    def to_input_dict(self) -> dict[str, object]:
        return {
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "direct_ownership_percentage": _decimal_text(self.direct_ownership_percentage),
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "interest_id": self.interest_id,
            "parent_entity_code": self.parent_entity_code,
            "prepared_by": self.prepared_by,
            "source_digest": self.source_digest,
            "subsidiary_entity_code": self.subsidiary_entity_code,
            "version": self.version,
        }


@dataclass(frozen=True)
class ConsolidationEliminationLine:
    """One reporting-currency line in a traceable elimination proposal."""

    line_id: str
    entity_code: str
    group_account_code: str
    account_type: ConsolidationAccountType
    amount: Money
    source_reference: str
    source_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_id", _identifier(self.line_id, "Elimination line identifier"))
        object.__setattr__(self, "entity_code", _identifier(self.entity_code, "Elimination entity"))
        object.__setattr__(
            self,
            "group_account_code",
            _identifier(self.group_account_code, "Elimination group account"),
        )
        object.__setattr__(self, "account_type", _account_type(self.account_type))
        if not isinstance(self.amount, Money):
            raise ConsolidationError("Elimination amount must be Money.")
        if self.amount.amount == 0:
            raise ConsolidationError("Elimination lines must have a non-zero amount.")
        object.__setattr__(self, "source_reference", _bounded_text(self.source_reference, "Elimination source"))
        object.__setattr__(self, "source_digest", _sha256(self.source_digest, "Elimination source digest"))

    def to_input_dict(self) -> dict[str, object]:
        return {
            "account_type": self.account_type,
            "amount": self.amount.to_canonical_dict(),
            "entity_code": self.entity_code,
            "group_account_code": self.group_account_code,
            "line_id": self.line_id,
            "source_digest": self.source_digest,
            "source_reference": self.source_reference,
        }


@dataclass(frozen=True)
class ConsolidationElimination:
    """Balancedness is verified in the group request where currency and entities are known."""

    elimination_id: str
    elimination_type: ConsolidationEliminationType
    version: str
    lines: tuple[ConsolidationEliminationLine, ...]
    prepared_by: str
    prepared_at: str
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "elimination_id", _identifier(self.elimination_id, "Elimination identifier"))
        object.__setattr__(self, "elimination_type", _elimination_type(self.elimination_type))
        object.__setattr__(self, "version", _semver(self.version, "Elimination version"))
        if not isinstance(self.lines, tuple) or not 2 <= len(self.lines) <= MAX_CONSOLIDATION_ELIMINATION_LINES:
            raise ConsolidationError("Elimination proposals require a bounded set of at least two lines.")
        if any(not isinstance(line, ConsolidationEliminationLine) for line in self.lines):
            raise ConsolidationError("Elimination proposal lines are invalid.")
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ConsolidationError("Elimination proposal line identifiers must be unique.")
        object.__setattr__(self, "lines", tuple(sorted(self.lines, key=lambda item: item.line_id)))
        object.__setattr__(self, "prepared_by", _identifier(self.prepared_by, "Elimination preparer"))
        object.__setattr__(self, "prepared_at", _timestamp(self.prepared_at, "Elimination preparation timestamp"))
        object.__setattr__(self, "rationale", _bounded_text(self.rationale, "Elimination rationale"))

    def to_input_dict(self) -> dict[str, object]:
        return {
            "elimination_id": self.elimination_id,
            "elimination_type": self.elimination_type,
            "lines": [line.to_input_dict() for line in self.lines],
            "prepared_at": self.prepared_at,
            "prepared_by": self.prepared_by,
            "rationale": self.rationale,
            "version": self.version,
        }


@dataclass(frozen=True)
class ConsolidationWorksheetRequest:
    """Closed input contract for one non-posting group worksheet."""

    translation_result: ConsolidationTranslationResult
    policy: ConsolidationLifecyclePolicy
    period_start_date: str
    period_end_date: str
    reporting_date: str
    ownership_interests: tuple[ConsolidationOwnershipInterest, ...]
    eliminations: tuple[ConsolidationElimination, ...]
    prepared_by: str
    prepared_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.translation_result, ConsolidationTranslationResult):
            raise ConsolidationError("Translation result is invalid.")
        verified = verify_consolidation_result_payload(self.translation_result.to_dict())
        object.__setattr__(self, "translation_result", verified)
        if not isinstance(self.policy, ConsolidationLifecyclePolicy):
            raise ConsolidationError("Consolidation lifecycle policy is invalid.")
        period_start = _iso_date(self.period_start_date, "Consolidation period start")
        period_end = _iso_date(self.period_end_date, "Consolidation period end")
        reporting_date = _iso_date(self.reporting_date, "Consolidation reporting date")
        if period_start > period_end:
            raise ConsolidationError("Consolidation period start must not follow its end.")
        if not period_start <= reporting_date <= period_end:
            raise ConsolidationError("Consolidation reporting date must be within the declared period.")
        object.__setattr__(self, "period_start_date", period_start)
        object.__setattr__(self, "period_end_date", period_end)
        object.__setattr__(self, "reporting_date", reporting_date)
        if (
            not isinstance(self.ownership_interests, tuple)
            or len(self.ownership_interests) > MAX_OWNERSHIP_INTERESTS
            or any(not isinstance(item, ConsolidationOwnershipInterest) for item in self.ownership_interests)
        ):
            raise ConsolidationError("Ownership interests are invalid or exceed the worksheet limit.")
        if len({item.interest_id for item in self.ownership_interests}) != len(self.ownership_interests):
            raise ConsolidationError("Ownership interest identifiers must be unique.")
        object.__setattr__(
            self,
            "ownership_interests",
            tuple(
                sorted(
                    self.ownership_interests,
                    key=lambda item: (
                        item.subsidiary_entity_code,
                        item.effective_from,
                        item.effective_to,
                        item.parent_entity_code,
                        item.interest_id,
                    ),
                )
            ),
        )
        if (
            not isinstance(self.eliminations, tuple)
            or len(self.eliminations) > MAX_CONSOLIDATION_ELIMINATIONS
            or any(not isinstance(item, ConsolidationElimination) for item in self.eliminations)
        ):
            raise ConsolidationError("Eliminations are invalid or exceed the worksheet limit.")
        if len({item.elimination_id for item in self.eliminations}) != len(self.eliminations):
            raise ConsolidationError("Elimination identifiers must be unique.")
        if sum(len(item.lines) for item in self.eliminations) > MAX_CONSOLIDATION_ELIMINATION_LINES:
            raise ConsolidationError("Elimination lines exceed the worksheet limit.")
        object.__setattr__(
            self,
            "eliminations",
            tuple(sorted(self.eliminations, key=lambda item: item.elimination_id)),
        )
        object.__setattr__(self, "prepared_by", _identifier(self.prepared_by, "Worksheet preparer"))
        prepared_at = _timestamp(self.prepared_at, "Worksheet preparation timestamp")
        if any(item.approved_at > prepared_at for item in self.ownership_interests):
            raise ConsolidationError("Ownership approval must not follow worksheet preparation.")
        if any(item.prepared_at > prepared_at for item in self.eliminations):
            raise ConsolidationError("Elimination preparation must not follow worksheet preparation.")
        object.__setattr__(self, "prepared_at", prepared_at)

    def to_input_dict(self) -> dict[str, object]:
        return {
            "eliminations": [item.to_input_dict() for item in self.eliminations],
            "ownership_interests": [item.to_input_dict() for item in self.ownership_interests],
            "period_end_date": self.period_end_date,
            "period_start_date": self.period_start_date,
            "policy": self.policy.to_dict(),
            "prepared_at": self.prepared_at,
            "prepared_by": self.prepared_by,
            "reporting_date": self.reporting_date,
            "translation_result": self.translation_result.to_dict(),
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_input_dict())


@dataclass(frozen=True)
class ConsolidationOwnershipAllocation:
    subsidiary_entity_code: str
    immediate_parent_entity_code: str
    direct_ownership_percentage: Decimal
    effective_group_ownership_percentage: Decimal
    non_controlling_percentage: Decimal
    ownership_path: tuple[str, ...]
    active_interest_id: str
    active_interest_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "active_interest_id": self.active_interest_id,
            "active_interest_ids": list(self.active_interest_ids),
            "direct_ownership_percentage": _decimal_text(self.direct_ownership_percentage),
            "effective_group_ownership_percentage": _decimal_text(
                self.effective_group_ownership_percentage
            ),
            "immediate_parent_entity_code": self.immediate_parent_entity_code,
            "non_controlling_percentage": _decimal_text(self.non_controlling_percentage),
            "ownership_path": list(self.ownership_path),
            "subsidiary_entity_code": self.subsidiary_entity_code,
        }


@dataclass(frozen=True)
class ConsolidationWorksheetAccount:
    group_account_code: str
    account_type: ConsolidationAccountType
    amount: Money
    source_references: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "account_type": self.account_type,
            "amount": self.amount.to_canonical_dict(),
            "group_account_code": self.group_account_code,
            "source_references": list(self.source_references),
        }


@dataclass(frozen=True)
class AppliedConsolidationElimination:
    elimination_id: str
    elimination_type: ConsolidationEliminationType
    version: str
    lines: tuple[ConsolidationEliminationLine, ...]
    balance: Money
    prepared_by: str
    prepared_at: str
    rationale: str
    posted: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "balance": self.balance.to_canonical_dict(),
            "elimination_id": self.elimination_id,
            "elimination_type": self.elimination_type,
            "lines": [line.to_input_dict() for line in self.lines],
            "posted": self.posted,
            "prepared_at": self.prepared_at,
            "prepared_by": self.prepared_by,
            "rationale": self.rationale,
            "version": self.version,
        }


@dataclass(frozen=True)
class NonControllingInterestAllocation:
    subsidiary_entity_code: str
    effective_group_ownership_percentage: Decimal
    non_controlling_percentage: Decimal
    net_assets: Money
    period_profit: Money
    nci_net_assets: Money
    nci_period_profit: Money
    unrounded_nci_net_assets: Decimal
    unrounded_nci_period_profit: Decimal
    nci_net_assets_rounding_delta: Decimal
    nci_period_profit_rounding_delta: Decimal
    net_assets_presentation_account_code: str
    profit_presentation_account_code: str
    posted: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "effective_group_ownership_percentage": _decimal_text(
                self.effective_group_ownership_percentage
            ),
            "nci_net_assets": self.nci_net_assets.to_canonical_dict(),
            "nci_net_assets_rounding_delta": _decimal_text(self.nci_net_assets_rounding_delta),
            "nci_period_profit": self.nci_period_profit.to_canonical_dict(),
            "nci_period_profit_rounding_delta": _decimal_text(self.nci_period_profit_rounding_delta),
            "net_assets": self.net_assets.to_canonical_dict(),
            "net_assets_presentation_account_code": self.net_assets_presentation_account_code,
            "non_controlling_percentage": _decimal_text(self.non_controlling_percentage),
            "period_profit": self.period_profit.to_canonical_dict(),
            "posted": self.posted,
            "profit_presentation_account_code": self.profit_presentation_account_code,
            "subsidiary_entity_code": self.subsidiary_entity_code,
            "unrounded_nci_net_assets": _decimal_text(self.unrounded_nci_net_assets),
            "unrounded_nci_period_profit": _decimal_text(self.unrounded_nci_period_profit),
        }


@dataclass(frozen=True)
class ConsolidationWorksheetResult:
    schema_version: int
    algorithm_version: str
    worksheet_id: str
    request_digest: str
    result_digest: str
    translation_result_digest: str
    group_code: str
    period_id: str
    reporting_currency: str
    period_start_date: str
    period_end_date: str
    reporting_date: str
    prepared_by: str
    prepared_at: str
    policy: ConsolidationLifecyclePolicy
    request: ConsolidationWorksheetRequest
    ownership_allocations: tuple[ConsolidationOwnershipAllocation, ...]
    nci_allocations: tuple[NonControllingInterestAllocation, ...]
    base_accounts: tuple[ConsolidationWorksheetAccount, ...]
    eliminations: tuple[AppliedConsolidationElimination, ...]
    worksheet_accounts: tuple[ConsolidationWorksheetAccount, ...]
    pre_elimination_balance: Money
    post_elimination_balance: Money
    posting_effect: Literal["none"] = "none"

    def _payload(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "base_account_count": len(self.base_accounts),
            "base_accounts": [item.to_dict() for item in self.base_accounts],
            "elimination_count": len(self.eliminations),
            "eliminations": [item.to_dict() for item in self.eliminations],
            "group_code": self.group_code,
            "nci_allocation_count": len(self.nci_allocations),
            "nci_allocations": [item.to_dict() for item in self.nci_allocations],
            "ownership_allocation_count": len(self.ownership_allocations),
            "ownership_allocations": [item.to_dict() for item in self.ownership_allocations],
            "period_end_date": self.period_end_date,
            "period_id": self.period_id,
            "period_start_date": self.period_start_date,
            "policy": self.policy.to_dict(),
            "policy_digest": self.policy.digest,
            "post_elimination_balance": self.post_elimination_balance.to_canonical_dict(),
            "posting_effect": self.posting_effect,
            "pre_elimination_balance": self.pre_elimination_balance.to_canonical_dict(),
            "prepared_at": self.prepared_at,
            "prepared_by": self.prepared_by,
            "reporting_currency": self.reporting_currency,
            "reporting_date": self.reporting_date,
            "request": self.request.to_input_dict(),
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "translation_result_digest": self.translation_result_digest,
            "worksheet_account_count": len(self.worksheet_accounts),
            "worksheet_accounts": [item.to_dict() for item in self.worksheet_accounts],
            "worksheet_id": self.worksheet_id,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self._payload()
        payload["result_digest"] = self.result_digest
        return payload


def _validate_ownership_history(
    interests: tuple[ConsolidationOwnershipInterest, ...],
    entities: frozenset[str],
) -> None:
    by_child: dict[str, list[ConsolidationOwnershipInterest]] = {}
    for interest in interests:
        if interest.parent_entity_code not in entities or interest.subsidiary_entity_code not in entities:
            raise ConsolidationError("Ownership interest entity is outside the translated group.")
        by_child.setdefault(interest.subsidiary_entity_code, []).append(interest)
    for child, records in by_child.items():
        previous_end: str | None = None
        for record in sorted(records, key=lambda item: (item.effective_from, item.effective_to, item.interest_id)):
            if previous_end is not None and (previous_end == "" or record.effective_from <= previous_end):
                raise ConsolidationError(f"Ownership effective-date intervals overlap for entity {child}.")
            previous_end = record.effective_to


def _ownership_allocations(
    request: ConsolidationWorksheetRequest,
    entities: frozenset[str],
) -> tuple[ConsolidationOwnershipAllocation, ...]:
    _validate_ownership_history(request.ownership_interests, entities)
    root = request.policy.parent_entity_code
    if root not in entities:
        raise ConsolidationError("Consolidation root entity is outside the translated group.")
    active = tuple(
        interest for interest in request.ownership_interests if interest.is_effective(request.reporting_date)
    )
    active_by_child: dict[str, ConsolidationOwnershipInterest] = {}
    for interest in active:
        if interest.subsidiary_entity_code == root:
            raise ConsolidationError("Consolidation root entity cannot have an active parent.")
        if interest.direct_ownership_percentage <= Decimal("0.5"):
            raise ConsolidationError("Full-consolidation ownership must establish control above 0.5.")
        if interest.subsidiary_entity_code in active_by_child:
            raise ConsolidationError("Each entity must have exactly one active ownership interest.")
        active_by_child[interest.subsidiary_entity_code] = interest
    expected_children = entities - {root}
    if set(active_by_child) != expected_children:
        raise ConsolidationError(
            "Each non-root consolidation entity must have exactly one active ownership interest."
        )

    allocations: list[ConsolidationOwnershipAllocation] = []
    for entity in sorted(expected_children):
        current = entity
        reverse_path = [entity]
        reverse_interest_ids: list[str] = []
        effective = Decimal("1")
        seen: set[str] = set()
        while current != root:
            if current in seen:
                raise ConsolidationError("Active consolidation ownership graph contains a cycle.")
            seen.add(current)
            current_interest = active_by_child.get(current)
            if current_interest is None:
                raise ConsolidationError("Active consolidation ownership graph is not rooted at the parent entity.")
            effective = _exact_multiply(effective, current_interest.direct_ownership_percentage)
            reverse_interest_ids.append(current_interest.interest_id)
            current = current_interest.parent_entity_code
            reverse_path.append(current)
        direct = active_by_child[entity]
        allocations.append(
            ConsolidationOwnershipAllocation(
                subsidiary_entity_code=entity,
                immediate_parent_entity_code=direct.parent_entity_code,
                direct_ownership_percentage=direct.direct_ownership_percentage,
                effective_group_ownership_percentage=effective,
                non_controlling_percentage=_exact_sum((Decimal("1"), -effective)),
                ownership_path=tuple(reversed(reverse_path)),
                active_interest_id=direct.interest_id,
                active_interest_ids=tuple(reversed(reverse_interest_ids)),
            )
        )
    return tuple(allocations)


def _account_tuple(
    accounts: dict[str, tuple[ConsolidationAccountType, Decimal, set[str]]],
    currency: str,
) -> tuple[ConsolidationWorksheetAccount, ...]:
    return tuple(
        ConsolidationWorksheetAccount(
            group_account_code=account_code,
            account_type=account_type,
            amount=Money.from_exact(amount, currency, strict_precision=True),
            source_references=tuple(sorted(sources)),
        )
        for account_code, (account_type, amount, sources) in sorted(accounts.items())
    )


def _add_account(
    accounts: dict[str, tuple[ConsolidationAccountType, Decimal, set[str]]],
    *,
    account_code: str,
    account_type: ConsolidationAccountType,
    amount: Decimal,
    source_reference: str,
) -> None:
    current = accounts.get(account_code)
    if current is None:
        accounts[account_code] = (account_type, amount, {source_reference})
        return
    current_type, current_amount, sources = current
    if current_type != account_type:
        raise ConsolidationError(f"Consolidation account type conflict for {account_code}.")
    accounts[account_code] = (
        current_type,
        _exact_sum((current_amount, amount)),
        {*sources, source_reference},
    )


def _nci_allocation(
    allocation: ConsolidationOwnershipAllocation,
    result: ConsolidationTranslationResult,
    policy: ConsolidationLifecyclePolicy,
) -> NonControllingInterestAllocation:
    entity_lines = tuple(
        line for line in result.lines if line.entity_code == allocation.subsidiary_entity_code
    )
    currency = result.reporting_currency
    net_assets_amount = _exact_sum(
        tuple(
            line.translated_amount.amount
            for line in entity_lines
            if line.account_type in {"Asset", "Liability"}
        )
    )
    period_profit_amount = -_exact_sum(
        tuple(
            line.translated_amount.amount
            for line in entity_lines
            if line.account_type in {"Income", "Expense"}
        )
    )
    net_assets = Money.from_exact(net_assets_amount, currency, strict_precision=True)
    period_profit = Money.from_exact(period_profit_amount, currency, strict_precision=True)
    unrounded_net_assets = _exact_multiply(net_assets.amount, allocation.non_controlling_percentage)
    unrounded_period_profit = _exact_multiply(period_profit.amount, allocation.non_controlling_percentage)
    nci_net_assets = Money.from_exact(unrounded_net_assets, currency)
    nci_period_profit = Money.from_exact(unrounded_period_profit, currency)
    return NonControllingInterestAllocation(
        subsidiary_entity_code=allocation.subsidiary_entity_code,
        effective_group_ownership_percentage=allocation.effective_group_ownership_percentage,
        non_controlling_percentage=allocation.non_controlling_percentage,
        net_assets=net_assets,
        period_profit=period_profit,
        nci_net_assets=nci_net_assets,
        nci_period_profit=nci_period_profit,
        unrounded_nci_net_assets=unrounded_net_assets,
        unrounded_nci_period_profit=unrounded_period_profit,
        nci_net_assets_rounding_delta=_exact_sum((nci_net_assets.amount, -unrounded_net_assets)),
        nci_period_profit_rounding_delta=_exact_sum((nci_period_profit.amount, -unrounded_period_profit)),
        net_assets_presentation_account_code=policy.nci_net_assets_presentation_account_code,
        profit_presentation_account_code=policy.nci_profit_presentation_account_code,
        posted=False,
    )


def prepare_consolidation_worksheet(
    request: ConsolidationWorksheetRequest,
) -> ConsolidationWorksheetResult:
    """Prepare a deterministic, balanced worksheet without creating a posting effect."""

    if not isinstance(request, ConsolidationWorksheetRequest):
        raise ConsolidationError("Consolidation worksheet request is invalid.")
    translation = request.translation_result
    entities = frozenset(line.entity_code for line in translation.lines)
    allocations = _ownership_allocations(request, entities)
    reporting_currency = translation.reporting_currency

    base: dict[str, tuple[ConsolidationAccountType, Decimal, set[str]]] = {}
    for account in translation.account_totals:
        _add_account(
            base,
            account_code=account.group_account_code,
            account_type=account.account_type,
            amount=account.amount.amount,
            source_reference=f"translation-result:{translation.run_id}",
        )
    adjustment = translation.translation_adjustment
    if adjustment.required or adjustment.amount.amount != 0:
        _add_account(
            base,
            account_code=adjustment.account_code,
            account_type=adjustment.account_type,
            amount=adjustment.amount.amount,
            source_reference=f"translation-adjustment:{translation.run_id}",
        )
    base_accounts = _account_tuple(base, reporting_currency)
    pre_balance = _money_sum(tuple(account.amount for account in base_accounts), reporting_currency)
    if pre_balance.amount != 0:
        raise ConsolidationError("Translated consolidation worksheet must balance before eliminations.")

    working = {
        code: (account_type, amount, set(sources))
        for code, (account_type, amount, sources) in base.items()
    }
    applied: list[AppliedConsolidationElimination] = []
    global_line_ids: set[str] = set()
    for elimination in request.eliminations:
        if len({line.entity_code for line in elimination.lines}) < 2:
            raise ConsolidationError("Elimination proposals must reference at least two group entities.")
        for line in elimination.lines:
            if line.line_id in global_line_ids:
                raise ConsolidationError("Elimination line identifiers must be unique across the worksheet.")
            global_line_ids.add(line.line_id)
            if line.entity_code not in entities:
                raise ConsolidationError("Elimination line entity is outside the translated group.")
            if line.amount.currency != reporting_currency:
                raise ConsolidationError("Elimination lines must use the reporting currency.")
        balance = _money_sum(tuple(line.amount for line in elimination.lines), reporting_currency)
        if balance.amount != 0:
            raise ConsolidationError("Every consolidation elimination must balance to zero.")
        for line in elimination.lines:
            _add_account(
                working,
                account_code=line.group_account_code,
                account_type=line.account_type,
                amount=line.amount.amount,
                source_reference=f"elimination:{elimination.elimination_id}:{line.line_id}",
            )
        applied.append(
            AppliedConsolidationElimination(
                elimination_id=elimination.elimination_id,
                elimination_type=elimination.elimination_type,
                version=elimination.version,
                lines=elimination.lines,
                balance=balance,
                prepared_by=elimination.prepared_by,
                prepared_at=elimination.prepared_at,
                rationale=elimination.rationale,
                posted=False,
            )
        )

    worksheet_accounts = _account_tuple(working, reporting_currency)
    post_balance = _money_sum(
        tuple(account.amount for account in worksheet_accounts),
        reporting_currency,
    )
    if post_balance.amount != 0:
        raise ConsolidationError("Consolidation worksheet must balance after eliminations.")
    nci = tuple(_nci_allocation(item, translation, request.policy) for item in allocations)
    request_digest = request.digest
    result = ConsolidationWorksheetResult(
        schema_version=CONSOLIDATION_WORKSHEET_SCHEMA_VERSION,
        algorithm_version=CONSOLIDATION_WORKSHEET_ALGORITHM_VERSION,
        worksheet_id=f"CWS-{request_digest[:20].upper()}",
        request_digest=request_digest,
        result_digest="",
        translation_result_digest=translation.result_digest,
        group_code=translation.group_code,
        period_id=translation.period_id,
        reporting_currency=reporting_currency,
        period_start_date=request.period_start_date,
        period_end_date=request.period_end_date,
        reporting_date=request.reporting_date,
        prepared_by=request.prepared_by,
        prepared_at=request.prepared_at,
        policy=request.policy,
        request=request,
        ownership_allocations=allocations,
        nci_allocations=nci,
        base_accounts=base_accounts,
        eliminations=tuple(applied),
        worksheet_accounts=worksheet_accounts,
        pre_elimination_balance=pre_balance,
        post_elimination_balance=post_balance,
        posting_effect="none",
    )
    return replace(result, result_digest=_digest(result._payload()))


_TOP_LEVEL_KEYS = frozenset(
    {
        "algorithm_version",
        "base_account_count",
        "base_accounts",
        "elimination_count",
        "eliminations",
        "group_code",
        "nci_allocation_count",
        "nci_allocations",
        "ownership_allocation_count",
        "ownership_allocations",
        "period_end_date",
        "period_id",
        "period_start_date",
        "policy",
        "policy_digest",
        "post_elimination_balance",
        "posting_effect",
        "pre_elimination_balance",
        "prepared_at",
        "prepared_by",
        "reporting_currency",
        "reporting_date",
        "request",
        "request_digest",
        "result_digest",
        "schema_version",
        "translation_result_digest",
        "worksheet_account_count",
        "worksheet_accounts",
        "worksheet_id",
    }
)
_REQUEST_KEYS = frozenset(
    {
        "eliminations",
        "ownership_interests",
        "period_end_date",
        "period_start_date",
        "policy",
        "prepared_at",
        "prepared_by",
        "reporting_date",
        "translation_result",
    }
)
_POLICY_KEYS = frozenset(
    {
        "nci_net_assets_presentation_account_code",
        "nci_profit_presentation_account_code",
        "parent_entity_code",
        "policy_id",
        "version",
    }
)
_OWNERSHIP_KEYS = frozenset(
    {
        "approved_at",
        "approved_by",
        "direct_ownership_percentage",
        "effective_from",
        "effective_to",
        "interest_id",
        "parent_entity_code",
        "prepared_by",
        "source_digest",
        "subsidiary_entity_code",
        "version",
    }
)
_ELIMINATION_KEYS = frozenset(
    {
        "elimination_id",
        "elimination_type",
        "lines",
        "prepared_at",
        "prepared_by",
        "rationale",
        "version",
    }
)
_ELIMINATION_LINE_KEYS = frozenset(
    {
        "account_type",
        "amount",
        "entity_code",
        "group_account_code",
        "line_id",
        "source_digest",
        "source_reference",
    }
)


def _exact_mapping(value: object, keys: frozenset[str], field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys or any(not isinstance(key, str) for key in value):
        raise ConsolidationError(f"{field} does not match its closed schema.")
    return cast(Mapping[str, object], value)


def verify_consolidation_worksheet_payload(
    payload: Mapping[str, object],
) -> ConsolidationWorksheetResult:
    """Reproduce a worksheet from its closed request and reject rehashed output tampering."""

    try:
        document = _exact_mapping(payload, _TOP_LEVEL_KEYS, "Consolidation worksheet")
        if (
            document["schema_version"] != CONSOLIDATION_WORKSHEET_SCHEMA_VERSION
            or document["algorithm_version"] != CONSOLIDATION_WORKSHEET_ALGORITHM_VERSION
            or document["posting_effect"] != "none"
        ):
            raise ConsolidationError("Consolidation worksheet runtime policy is unsupported.")
        request_payload = _exact_mapping(document["request"], _REQUEST_KEYS, "Consolidation worksheet request")
        translation_payload = cast(Mapping[str, object], request_payload["translation_result"])
        translation = verify_consolidation_result_payload(translation_payload)
        policy_payload = _exact_mapping(request_payload["policy"], _POLICY_KEYS, "Consolidation lifecycle policy")
        policy = ConsolidationLifecyclePolicy(
            policy_id=cast(str, policy_payload["policy_id"]),
            version=cast(str, policy_payload["version"]),
            parent_entity_code=cast(str, policy_payload["parent_entity_code"]),
            nci_net_assets_presentation_account_code=cast(
                str, policy_payload["nci_net_assets_presentation_account_code"]
            ),
            nci_profit_presentation_account_code=cast(
                str, policy_payload["nci_profit_presentation_account_code"]
            ),
        )
        raw_ownership = request_payload["ownership_interests"]
        if not isinstance(raw_ownership, list):
            raise ConsolidationError("Consolidation ownership request is invalid.")
        ownerships: list[ConsolidationOwnershipInterest] = []
        for raw in raw_ownership:
            item = _exact_mapping(raw, _OWNERSHIP_KEYS, "Consolidation ownership interest")
            ownerships.append(
                ConsolidationOwnershipInterest(
                    interest_id=cast(str, item["interest_id"]),
                    parent_entity_code=cast(str, item["parent_entity_code"]),
                    subsidiary_entity_code=cast(str, item["subsidiary_entity_code"]),
                    direct_ownership_percentage=_decimal_from_text(
                        item["direct_ownership_percentage"], "Direct ownership percentage"
                    ),
                    effective_from=cast(str, item["effective_from"]),
                    effective_to=cast(str, item["effective_to"]),
                    version=cast(str, item["version"]),
                    source_digest=cast(str, item["source_digest"]),
                    prepared_by=cast(str, item["prepared_by"]),
                    approved_by=cast(str, item["approved_by"]),
                    approved_at=cast(str, item["approved_at"]),
                )
            )
        raw_eliminations = request_payload["eliminations"]
        if not isinstance(raw_eliminations, list):
            raise ConsolidationError("Consolidation elimination request is invalid.")
        eliminations: list[ConsolidationElimination] = []
        for raw in raw_eliminations:
            item = _exact_mapping(raw, _ELIMINATION_KEYS, "Consolidation elimination")
            raw_lines = item["lines"]
            if not isinstance(raw_lines, list):
                raise ConsolidationError("Consolidation elimination lines are invalid.")
            lines: list[ConsolidationEliminationLine] = []
            for raw_line in raw_lines:
                line = _exact_mapping(raw_line, _ELIMINATION_LINE_KEYS, "Consolidation elimination line")
                lines.append(
                    ConsolidationEliminationLine(
                        line_id=cast(str, line["line_id"]),
                        entity_code=cast(str, line["entity_code"]),
                        group_account_code=cast(str, line["group_account_code"]),
                        account_type=cast(ConsolidationAccountType, line["account_type"]),
                        amount=Money.from_canonical_dict(cast(Mapping[str, object], line["amount"])),
                        source_reference=cast(str, line["source_reference"]),
                        source_digest=cast(str, line["source_digest"]),
                    )
                )
            eliminations.append(
                ConsolidationElimination(
                    elimination_id=cast(str, item["elimination_id"]),
                    elimination_type=cast(ConsolidationEliminationType, item["elimination_type"]),
                    version=cast(str, item["version"]),
                    lines=tuple(lines),
                    prepared_by=cast(str, item["prepared_by"]),
                    prepared_at=cast(str, item["prepared_at"]),
                    rationale=cast(str, item["rationale"]),
                )
            )
        request = ConsolidationWorksheetRequest(
            translation_result=translation,
            policy=policy,
            period_start_date=cast(str, request_payload["period_start_date"]),
            period_end_date=cast(str, request_payload["period_end_date"]),
            reporting_date=cast(str, request_payload["reporting_date"]),
            ownership_interests=tuple(ownerships),
            eliminations=tuple(eliminations),
            prepared_by=cast(str, request_payload["prepared_by"]),
            prepared_at=cast(str, request_payload["prepared_at"]),
        )
        reproduced = prepare_consolidation_worksheet(request)
    except ConsolidationError:
        raise
    except (ArithmeticError, KeyError, TypeError, ValueError, InvalidAmountError) as exc:
        raise ConsolidationError("Consolidation worksheet payload is invalid.") from exc
    expected = reproduced.to_dict()
    supplied = dict(document)
    if not hmac.compare_digest(
        json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        json.dumps(supplied, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
    ):
        raise ConsolidationError("Consolidation worksheet payload does not reproduce under its declared inputs.")
    return reproduced
