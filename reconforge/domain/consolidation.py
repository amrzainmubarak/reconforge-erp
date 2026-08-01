"""Deterministic, explainable financial-consolidation translation invariants."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Literal, cast

from reconforge.utils.money import CurrencyRegistry, ExchangeRate, InvalidAmountError, Money

CONSOLIDATION_TRANSLATION_SCHEMA_VERSION = 1
CONSOLIDATION_TRANSLATION_ALGORITHM_VERSION = "consolidation-translation-v1"
MAX_CONSOLIDATION_BALANCE_LINES = 100_000
MAX_CONSOLIDATION_RATES = 10_000

TranslationRateType = Literal["closing", "average", "historical"]
ConsolidationAccountType = Literal["Asset", "Liability", "Equity", "Income", "Expense"]

_RATE_TYPES = frozenset({"closing", "average", "historical"})
_ACCOUNT_TYPES = frozenset({"Asset", "Liability", "Equity", "Income", "Expense"})
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_SEMVER_PATTERN = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_RUN_ID_PATTERN = re.compile(r"^CON-[A-F0-9]{20}$")
_DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


class ConsolidationError(ValueError):
    """Raised when consolidation inputs or artifacts violate financial invariants."""


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


def _bounded_text(value: object, field: str, *, maximum: int = 240) -> str:
    if not isinstance(value, str):
        raise ConsolidationError(f"{field} is invalid.")
    clean = value.strip()
    if not clean or len(clean) > maximum or any(ord(character) < 32 for character in clean):
        raise ConsolidationError(f"{field} is invalid.")
    return clean


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


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ConsolidationError(f"{field} must be a finite Decimal.")
    if positive and value <= 0:
        raise ConsolidationError(f"{field} must be greater than zero.")
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


def _rate_type(value: object) -> TranslationRateType:
    if value not in _RATE_TYPES:
        raise ConsolidationError("Translation rate type is not supported.")
    return cast(TranslationRateType, value)


def _account_type(value: object) -> ConsolidationAccountType:
    if value not in _ACCOUNT_TYPES:
        raise ConsolidationError("Consolidation account type is not supported.")
    return cast(ConsolidationAccountType, value)


@dataclass(frozen=True)
class ConsolidationBalance:
    """One signed, traceable account balance from a balanced entity trial balance."""

    source_line_id: str
    source_trial_balance_digest: str
    entity_code: str
    source_account_code: str
    group_account_code: str
    account_type: ConsolidationAccountType
    period_id: str
    amount: Decimal
    currency: str
    rate_type: TranslationRateType
    rate_bucket: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_line_id", _identifier(self.source_line_id, "Source line identifier"))
        object.__setattr__(
            self,
            "source_trial_balance_digest",
            _sha256(self.source_trial_balance_digest, "Source trial-balance digest"),
        )
        object.__setattr__(self, "entity_code", _identifier(self.entity_code, "Entity code"))
        object.__setattr__(
            self, "source_account_code", _identifier(self.source_account_code, "Source account code")
        )
        object.__setattr__(self, "group_account_code", _identifier(self.group_account_code, "Group account code"))
        object.__setattr__(self, "account_type", _account_type(self.account_type))
        object.__setattr__(self, "period_id", _identifier(self.period_id, "Fiscal-period identifier"))
        object.__setattr__(self, "rate_type", _rate_type(self.rate_type))
        object.__setattr__(self, "rate_bucket", _identifier(self.rate_bucket, "Translation-rate bucket"))
        amount = _decimal(self.amount, "Consolidation amount")
        try:
            money = Money.from_exact(amount, self.currency, strict_precision=True)
        except InvalidAmountError as exc:
            if "precision" in str(exc):
                raise ConsolidationError("Consolidation amount exceeds currency precision.") from exc
            raise ConsolidationError("Consolidation amount currency policy is invalid.") from exc
        object.__setattr__(self, "amount", money.amount)
        object.__setattr__(self, "currency", money.currency)

    def to_input_dict(self) -> dict[str, object]:
        money = Money.from_exact(self.amount, self.currency, strict_precision=True)
        return {
            "account_type": self.account_type,
            "amount": money.to_canonical_dict(),
            "currency": self.currency,
            "entity_code": self.entity_code,
            "group_account_code": self.group_account_code,
            "period_id": self.period_id,
            "rate_type": self.rate_type,
            "rate_bucket": self.rate_bucket,
            "source_account_code": self.source_account_code,
            "source_line_id": self.source_line_id,
            "source_trial_balance_digest": self.source_trial_balance_digest,
        }


@dataclass(frozen=True)
class ConsolidationRate:
    """One approved, source-bound period rate selected by an exact closed key."""

    rate_id: str
    period_id: str
    rate_type: TranslationRateType
    base_currency: str
    reporting_currency: str
    rate: Decimal
    source: str
    source_digest: str
    effective_at: str
    rate_bucket: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate_id", _identifier(self.rate_id, "Translation-rate identifier"))
        object.__setattr__(self, "period_id", _identifier(self.period_id, "Translation-rate period"))
        object.__setattr__(self, "rate_type", _rate_type(self.rate_type))
        object.__setattr__(self, "rate_bucket", _identifier(self.rate_bucket, "Translation-rate bucket"))
        rate = _decimal(self.rate, "Translation rate", positive=True)
        source = _bounded_text(self.source, "Translation-rate source")
        source_digest = _sha256(self.source_digest, "Translation-rate source digest")
        effective_at = _timestamp(self.effective_at, "Translation-rate effective timestamp")
        try:
            exchange_rate = ExchangeRate(
                base_currency=self.base_currency,
                quote_currency=self.reporting_currency,
                rate=rate,
                source=source,
                effective_at=effective_at,
            )
        except InvalidAmountError as exc:
            raise ConsolidationError("Translation-rate currency policy is invalid.") from exc
        if exchange_rate.base_currency == exchange_rate.quote_currency:
            raise ConsolidationError("Same-currency translation uses the explicit identity rule, not a supplied rate.")
        object.__setattr__(self, "base_currency", exchange_rate.base_currency)
        object.__setattr__(self, "reporting_currency", exchange_rate.quote_currency)
        object.__setattr__(self, "rate", exchange_rate.rate)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_digest", source_digest)
        object.__setattr__(self, "effective_at", effective_at)

    @property
    def key(self) -> tuple[str, str, str, TranslationRateType, str]:
        return (
            self.period_id,
            self.base_currency,
            self.reporting_currency,
            self.rate_type,
            self.rate_bucket,
        )

    def to_input_dict(self) -> dict[str, object]:
        return {
            "base_currency": self.base_currency,
            "effective_at": self.effective_at,
            "period_id": self.period_id,
            "rate": _decimal_text(self.rate),
            "rate_id": self.rate_id,
            "rate_type": self.rate_type,
            "rate_bucket": self.rate_bucket,
            "reporting_currency": self.reporting_currency,
            "source": self.source,
            "source_digest": self.source_digest,
        }


@dataclass(frozen=True)
class ConsolidationPolicy:
    """Operator-approved translation policy without embedded accounting-law claims."""

    policy_id: str
    version: str
    translation_adjustment_account_code: str
    translation_adjustment_account_type: ConsolidationAccountType = "Equity"

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "Consolidation policy identifier"))
        if not isinstance(self.version, str) or not _SEMVER_PATTERN.fullmatch(self.version):
            raise ConsolidationError("Consolidation policy version must be semantic versioning.")
        object.__setattr__(
            self,
            "translation_adjustment_account_code",
            _identifier(self.translation_adjustment_account_code, "Translation-adjustment account code"),
        )
        object.__setattr__(
            self,
            "translation_adjustment_account_type",
            _account_type(self.translation_adjustment_account_type),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "translation_adjustment_account_code": self.translation_adjustment_account_code,
            "translation_adjustment_account_type": self.translation_adjustment_account_type,
            "version": self.version,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class ConsolidationRequest:
    """Complete deterministic input to one translation calculation."""

    group_code: str
    period_id: str
    reporting_currency: str
    actor_id: str
    calculated_at: str
    policy: ConsolidationPolicy
    balances: tuple[ConsolidationBalance, ...]
    rates: tuple[ConsolidationRate, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_code", _identifier(self.group_code, "Consolidation group code"))
        object.__setattr__(self, "period_id", _identifier(self.period_id, "Consolidation period"))
        object.__setattr__(self, "actor_id", _identifier(self.actor_id, "Consolidation actor identifier"))
        object.__setattr__(self, "calculated_at", _timestamp(self.calculated_at, "Calculation timestamp"))
        if not isinstance(self.policy, ConsolidationPolicy):
            raise ConsolidationError("Consolidation policy is invalid.")
        try:
            reporting_currency = CurrencyRegistry.resolve(self.reporting_currency).spec.code
        except InvalidAmountError as exc:
            raise ConsolidationError("Reporting currency policy is invalid.") from exc
        object.__setattr__(self, "reporting_currency", reporting_currency)
        try:
            balances = tuple(self.balances)
            rates = tuple(self.rates)
        except TypeError as exc:
            raise ConsolidationError("Consolidation balances and rates must be finite collections.") from exc
        if not balances or len(balances) > MAX_CONSOLIDATION_BALANCE_LINES:
            raise ConsolidationError("Consolidation balance-line count is outside the supported boundary.")
        if len(rates) > MAX_CONSOLIDATION_RATES:
            raise ConsolidationError("Consolidation rate count is outside the supported boundary.")
        if any(not isinstance(record, ConsolidationBalance) for record in balances):
            raise ConsolidationError("Consolidation balance collection is invalid.")
        if any(not isinstance(record, ConsolidationRate) for record in rates):
            raise ConsolidationError("Consolidation rate collection is invalid.")
        object.__setattr__(self, "balances", balances)
        object.__setattr__(self, "rates", rates)
        self._validate_balances()
        self._validate_rates()

    def _validate_balances(self) -> None:
        if len({record.source_line_id for record in self.balances}) != len(self.balances):
            raise ConsolidationError("Consolidation source line identities must be unique.")
        entities = {record.entity_code for record in self.balances}
        if len(entities) < 2:
            raise ConsolidationError("Consolidation requires at least two legal entities.")
        entity_currencies: dict[str, set[str]] = {}
        entity_digests: dict[str, set[str]] = {}
        entity_amounts: dict[str, list[Decimal]] = {}
        group_policies: dict[str, tuple[ConsolidationAccountType, TranslationRateType]] = {}
        for record in self.balances:
            if record.period_id != self.period_id:
                raise ConsolidationError("Consolidation balance period does not match the requested period.")
            if record.group_account_code == self.policy.translation_adjustment_account_code:
                raise ConsolidationError("Translation-adjustment account must not collide with an input group account.")
            entity_currencies.setdefault(record.entity_code, set()).add(record.currency)
            entity_digests.setdefault(record.entity_code, set()).add(record.source_trial_balance_digest)
            entity_amounts.setdefault(record.entity_code, []).append(record.amount)
            policy_key = (record.account_type, record.rate_type)
            previous = group_policies.setdefault(record.group_account_code, policy_key)
            if previous != policy_key:
                raise ConsolidationError("Consolidation group-account translation policy is inconsistent.")
        for entity in sorted(entities):
            if len(entity_currencies[entity]) != 1:
                raise ConsolidationError("Each consolidated entity must use exactly one functional currency.")
            if len(entity_digests[entity]) != 1:
                raise ConsolidationError("Each consolidated entity must reference one source trial-balance digest.")
            if _exact_sum(tuple(entity_amounts[entity])) != 0:
                raise ConsolidationError("A source trial balance is not balanced; translation refused.")

    def _validate_rates(self) -> None:
        rate_ids = {record.rate_id for record in self.rates}
        if len(rate_ids) != len(self.rates):
            raise ConsolidationError("Consolidation rate identities must be unique.")
        rate_map: dict[
            tuple[str, str, str, TranslationRateType, str], ConsolidationRate
        ] = {}
        for record in self.rates:
            if record.period_id != self.period_id:
                raise ConsolidationError("Translation-rate period does not match the requested period.")
            if record.reporting_currency != self.reporting_currency:
                raise ConsolidationError("Translation-rate reporting currency does not match the request.")
            if record.key in rate_map:
                raise ConsolidationError("Consolidation translation rate keys must be unique.")
            rate_map[record.key] = record
        required_keys = {
            (
                self.period_id,
                record.currency,
                self.reporting_currency,
                record.rate_type,
                record.rate_bucket,
            )
            for record in self.balances
            if record.currency != self.reporting_currency
        }
        missing = required_keys - set(rate_map)
        if missing:
            raise ConsolidationError("A required translation rate is missing.")
        unused = set(rate_map) - required_keys
        if unused:
            raise ConsolidationError("A supplied translation rate is unused.")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "balances": [
                record.to_input_dict()
                for record in sorted(
                    self.balances,
                    key=lambda item: (
                        item.entity_code,
                        item.group_account_code,
                        item.source_account_code,
                        item.source_line_id,
                    ),
                )
            ],
            "calculated_at": self.calculated_at,
            "currency_registry": CurrencyRegistry.manifest().to_dict(),
            "group_code": self.group_code,
            "period_id": self.period_id,
            "policy": self.policy.to_dict(),
            "policy_digest": self.policy.digest,
            "rates": [
                record.to_input_dict()
                for record in sorted(self.rates, key=lambda item: (item.key, item.rate_id))
            ],
            "reporting_currency": self.reporting_currency,
            "schema_version": CONSOLIDATION_TRANSLATION_SCHEMA_VERSION,
        }

    @property
    def digest(self) -> str:
        return _digest(self.canonical_payload())


@dataclass(frozen=True)
class TranslatedBalanceLine:
    source_line_id: str
    source_trial_balance_digest: str
    entity_code: str
    source_account_code: str
    group_account_code: str
    account_type: ConsolidationAccountType
    period_id: str
    rate_type: TranslationRateType
    rate_bucket: str
    original_amount: Money
    translated_amount: Money
    unrounded_translated_amount: Decimal
    rounding_delta: Decimal
    rate_id: str
    rate: Decimal
    rate_source: str
    rate_source_digest: str
    rate_effective_at: str
    selection_reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "account_type": self.account_type,
            "entity_code": self.entity_code,
            "group_account_code": self.group_account_code,
            "original_amount": self.original_amount.to_canonical_dict(),
            "period_id": self.period_id,
            "rate": _decimal_text(self.rate),
            "rate_effective_at": self.rate_effective_at,
            "rate_id": self.rate_id,
            "rate_source": self.rate_source,
            "rate_source_digest": self.rate_source_digest,
            "rate_type": self.rate_type,
            "rate_bucket": self.rate_bucket,
            "rounding_delta": _decimal_text(self.rounding_delta),
            "selection_reason": self.selection_reason,
            "source_account_code": self.source_account_code,
            "source_line_id": self.source_line_id,
            "source_trial_balance_digest": self.source_trial_balance_digest,
            "translated_amount": self.translated_amount.to_canonical_dict(),
            "unrounded_translated_amount": _decimal_text(self.unrounded_translated_amount),
        }


@dataclass(frozen=True)
class ConsolidatedAccountBalance:
    group_account_code: str
    account_type: ConsolidationAccountType
    amount: Money
    contributing_line_ids: tuple[str, ...]
    contributing_entity_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "account_type": self.account_type,
            "amount": self.amount.to_canonical_dict(),
            "contributing_entity_codes": list(self.contributing_entity_codes),
            "contributing_line_ids": list(self.contributing_line_ids),
            "group_account_code": self.group_account_code,
        }


@dataclass(frozen=True)
class TranslationAdjustmentProposal:
    account_code: str
    account_type: ConsolidationAccountType
    amount: Money
    required: bool
    posted: Literal[False]
    reason_code: Literal["TRANSLATION_BALANCING_ADJUSTMENT"] = "TRANSLATION_BALANCING_ADJUSTMENT"

    def to_dict(self) -> dict[str, object]:
        return {
            "account_code": self.account_code,
            "account_type": self.account_type,
            "amount": self.amount.to_canonical_dict(),
            "posted": self.posted,
            "reason_code": self.reason_code,
            "required": self.required,
        }


@dataclass(frozen=True)
class ConsolidationTranslationResult:
    schema_version: int
    algorithm_version: str
    run_id: str
    request_digest: str
    result_digest: str
    group_code: str
    period_id: str
    reporting_currency: str
    actor_id: str
    calculated_at: str
    policy: ConsolidationPolicy
    currency_registry: dict[str, object]
    lines: tuple[TranslatedBalanceLine, ...]
    account_totals: tuple[ConsolidatedAccountBalance, ...]
    pre_adjustment_balance: Money
    translation_adjustment: TranslationAdjustmentProposal
    post_adjustment_balance: Money
    unrounded_translation_difference: Decimal
    rounding_delta: Decimal

    def _payload(self) -> dict[str, object]:
        return {
            "account_count": len(self.account_totals),
            "account_totals": [record.to_dict() for record in self.account_totals],
            "actor_id": self.actor_id,
            "algorithm_version": self.algorithm_version,
            "calculated_at": self.calculated_at,
            "currency_registry": dict(self.currency_registry),
            "entity_count": len({record.entity_code for record in self.lines}),
            "group_code": self.group_code,
            "line_count": len(self.lines),
            "lines": [record.to_dict() for record in self.lines],
            "period_id": self.period_id,
            "policy": self.policy.to_dict(),
            "policy_digest": self.policy.digest,
            "post_adjustment_balance": self.post_adjustment_balance.to_canonical_dict(),
            "posting_effect": "none",
            "pre_adjustment_balance": self.pre_adjustment_balance.to_canonical_dict(),
            "reporting_currency": self.reporting_currency,
            "request_digest": self.request_digest,
            "rounding_delta": _decimal_text(self.rounding_delta),
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "translation_adjustment": self.translation_adjustment.to_dict(),
            "unrounded_translation_difference": _decimal_text(self.unrounded_translation_difference),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "result_digest": self.result_digest}


def translate_consolidation(request: ConsolidationRequest) -> ConsolidationTranslationResult:
    """Translate balanced entity trial balances and expose, but never post, the CTA."""

    if not isinstance(request, ConsolidationRequest):
        raise ConsolidationError("Consolidation request is invalid.")
    rate_map = {record.key: record for record in request.rates}
    lines: list[TranslatedBalanceLine] = []
    for balance in sorted(
        request.balances,
        key=lambda item: (item.entity_code, item.group_account_code, item.source_account_code, item.source_line_id),
    ):
        original = Money.from_exact(balance.amount, balance.currency, strict_precision=True)
        if balance.currency == request.reporting_currency:
            rate_value = Decimal("1")
            translated = Money.from_exact(original.amount, request.reporting_currency, strict_precision=True)
            unrounded = original.amount
            rate_id = f"IDENTITY-{request.reporting_currency}"
            rate_source = "currency-identity"
            rate_source_digest = hashlib.sha256(
                f"same-currency-identity-v1:{request.reporting_currency}".encode("ascii")
            ).hexdigest()
            rate_effective_at = ""
            selection_reason = "same-currency-identity-v1"
        else:
            selected = rate_map[
                (
                    request.period_id,
                    balance.currency,
                    request.reporting_currency,
                    balance.rate_type,
                    balance.rate_bucket,
                )
            ]
            exchange = ExchangeRate(
                base_currency=selected.base_currency,
                quote_currency=selected.reporting_currency,
                rate=selected.rate,
                source=selected.source,
                effective_at=selected.effective_at,
            )
            rate_value = selected.rate
            unrounded = _exact_multiply(original.amount, rate_value)
            translated = exchange.convert(original)
            rate_id = selected.rate_id
            rate_source = selected.source
            rate_source_digest = selected.source_digest
            rate_effective_at = selected.effective_at
            selection_reason = "exact-period-currency-rate-type-v1"
        rounding_delta = _exact_sum((translated.amount, -unrounded))
        lines.append(
            TranslatedBalanceLine(
                source_line_id=balance.source_line_id,
                source_trial_balance_digest=balance.source_trial_balance_digest,
                entity_code=balance.entity_code,
                source_account_code=balance.source_account_code,
                group_account_code=balance.group_account_code,
                account_type=balance.account_type,
                period_id=balance.period_id,
                rate_type=balance.rate_type,
                rate_bucket=balance.rate_bucket,
                original_amount=original,
                translated_amount=translated,
                unrounded_translated_amount=unrounded,
                rounding_delta=rounding_delta,
                rate_id=rate_id,
                rate=rate_value,
                rate_source=rate_source,
                rate_source_digest=rate_source_digest,
                rate_effective_at=rate_effective_at,
                selection_reason=selection_reason,
            )
        )

    by_account: dict[str, list[TranslatedBalanceLine]] = {}
    for line in lines:
        by_account.setdefault(line.group_account_code, []).append(line)
    account_totals: list[ConsolidatedAccountBalance] = []
    for account_code in sorted(by_account):
        contributors = by_account[account_code]
        amount = Money.from_exact("0", request.reporting_currency, strict_precision=True)
        for contributor in contributors:
            amount = amount + contributor.translated_amount
        account_totals.append(
            ConsolidatedAccountBalance(
                group_account_code=account_code,
                account_type=contributors[0].account_type,
                amount=amount,
                contributing_line_ids=tuple(sorted(record.source_line_id for record in contributors)),
                contributing_entity_codes=tuple(sorted({record.entity_code for record in contributors})),
            )
        )

    pre_adjustment = Money.from_exact("0", request.reporting_currency, strict_precision=True)
    for account in account_totals:
        pre_adjustment = pre_adjustment + account.amount
    adjustment_amount = -pre_adjustment
    adjustment = TranslationAdjustmentProposal(
        account_code=request.policy.translation_adjustment_account_code,
        account_type=request.policy.translation_adjustment_account_type,
        amount=adjustment_amount,
        required=adjustment_amount.amount != 0,
        posted=False,
    )
    post_adjustment = pre_adjustment + adjustment.amount
    unrounded_translation_difference = _exact_sum(
        tuple(record.unrounded_translated_amount for record in lines)
    )
    rounding_delta = _exact_sum(tuple(record.rounding_delta for record in lines))
    request_digest = request.digest
    result = ConsolidationTranslationResult(
        schema_version=CONSOLIDATION_TRANSLATION_SCHEMA_VERSION,
        algorithm_version=CONSOLIDATION_TRANSLATION_ALGORITHM_VERSION,
        run_id=f"CON-{request_digest[:20].upper()}",
        request_digest=request_digest,
        result_digest="",
        group_code=request.group_code,
        period_id=request.period_id,
        reporting_currency=request.reporting_currency,
        actor_id=request.actor_id,
        calculated_at=request.calculated_at,
        policy=request.policy,
        currency_registry=CurrencyRegistry.manifest().to_dict(),
        lines=tuple(lines),
        account_totals=tuple(account_totals),
        pre_adjustment_balance=pre_adjustment,
        translation_adjustment=adjustment,
        post_adjustment_balance=post_adjustment,
        unrounded_translation_difference=unrounded_translation_difference,
        rounding_delta=rounding_delta,
    )
    return replace(result, result_digest=_digest(result._payload()))


_TOP_LEVEL_KEYS = frozenset(
    {
        "account_count",
        "account_totals",
        "actor_id",
        "algorithm_version",
        "calculated_at",
        "currency_registry",
        "entity_count",
        "group_code",
        "line_count",
        "lines",
        "period_id",
        "policy",
        "policy_digest",
        "post_adjustment_balance",
        "posting_effect",
        "pre_adjustment_balance",
        "reporting_currency",
        "request_digest",
        "result_digest",
        "rounding_delta",
        "run_id",
        "schema_version",
        "translation_adjustment",
        "unrounded_translation_difference",
    }
)
_LINE_KEYS = frozenset(
    {
        "account_type",
        "entity_code",
        "group_account_code",
        "original_amount",
        "period_id",
        "rate",
        "rate_effective_at",
        "rate_id",
        "rate_source",
        "rate_source_digest",
        "rate_type",
        "rate_bucket",
        "rounding_delta",
        "selection_reason",
        "source_account_code",
        "source_line_id",
        "source_trial_balance_digest",
        "translated_amount",
        "unrounded_translated_amount",
    }
)
_POLICY_KEYS = frozenset(
    {
        "policy_id",
        "translation_adjustment_account_code",
        "translation_adjustment_account_type",
        "version",
    }
)


def _exact_mapping(value: object, keys: frozenset[str], field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys or any(not isinstance(key, str) for key in value):
        raise ConsolidationError(f"{field} does not match its closed schema.")
    return cast(Mapping[str, object], value)


def verify_consolidation_result_payload(payload: Mapping[str, object]) -> ConsolidationTranslationResult:
    """Rebuild a schema-v1 result from declared inputs and reject rehashed financial tampering."""

    try:
        document = _exact_mapping(payload, _TOP_LEVEL_KEYS, "Consolidation result")
        if (
            document["schema_version"] != CONSOLIDATION_TRANSLATION_SCHEMA_VERSION
            or document["algorithm_version"] != CONSOLIDATION_TRANSLATION_ALGORITHM_VERSION
            or document["posting_effect"] != "none"
            or document["currency_registry"] != CurrencyRegistry.manifest().to_dict()
        ):
            raise ConsolidationError("Consolidation result runtime policy is unsupported.")
        policy_payload = _exact_mapping(document["policy"], _POLICY_KEYS, "Consolidation policy")
        policy = ConsolidationPolicy(
            policy_id=cast(str, policy_payload["policy_id"]),
            version=cast(str, policy_payload["version"]),
            translation_adjustment_account_code=cast(str, policy_payload["translation_adjustment_account_code"]),
            translation_adjustment_account_type=cast(
                ConsolidationAccountType, policy_payload["translation_adjustment_account_type"]
            ),
        )
        raw_lines = document["lines"]
        if not isinstance(raw_lines, list) or not raw_lines:
            raise ConsolidationError("Consolidation result lines are invalid.")
        balances: list[ConsolidationBalance] = []
        rates_by_key: dict[
            tuple[str, str, str, TranslationRateType, str], ConsolidationRate
        ] = {}
        for raw_line in raw_lines:
            line = _exact_mapping(raw_line, _LINE_KEYS, "Consolidation result line")
            original_payload = cast(Mapping[str, object], line["original_amount"])
            original = Money.from_canonical_dict(original_payload)
            Money.from_canonical_dict(cast(Mapping[str, object], line["translated_amount"]))
            balance = ConsolidationBalance(
                source_line_id=cast(str, line["source_line_id"]),
                source_trial_balance_digest=cast(str, line["source_trial_balance_digest"]),
                entity_code=cast(str, line["entity_code"]),
                source_account_code=cast(str, line["source_account_code"]),
                group_account_code=cast(str, line["group_account_code"]),
                account_type=cast(ConsolidationAccountType, line["account_type"]),
                period_id=cast(str, line["period_id"]),
                amount=original.amount,
                currency=original.currency,
                rate_type=cast(TranslationRateType, line["rate_type"]),
                rate_bucket=cast(str, line["rate_bucket"]),
            )
            balances.append(balance)
            if line["selection_reason"] == "same-currency-identity-v1":
                if (
                    line["rate_id"] != f"IDENTITY-{original.currency}"
                    or line["rate"] != "1"
                    or line["rate_effective_at"] != ""
                ):
                    raise ConsolidationError("Consolidation identity-rate lineage is invalid.")
                continue
            if line["selection_reason"] != "exact-period-currency-rate-type-v1":
                raise ConsolidationError("Consolidation rate-selection reason is invalid.")
            rate = ConsolidationRate(
                rate_id=cast(str, line["rate_id"]),
                period_id=cast(str, line["period_id"]),
                rate_type=cast(TranslationRateType, line["rate_type"]),
                base_currency=original.currency,
                reporting_currency=cast(str, document["reporting_currency"]),
                rate=_decimal_from_text(line["rate"], "Translation rate"),
                source=cast(str, line["rate_source"]),
                source_digest=cast(str, line["rate_source_digest"]),
                effective_at=cast(str, line["rate_effective_at"]),
                rate_bucket=cast(str, line["rate_bucket"]),
            )
            previous = rates_by_key.setdefault(rate.key, rate)
            if previous != rate:
                raise ConsolidationError("Consolidation result contains inconsistent reused rate lineage.")
        request = ConsolidationRequest(
            group_code=cast(str, document["group_code"]),
            period_id=cast(str, document["period_id"]),
            reporting_currency=cast(str, document["reporting_currency"]),
            actor_id=cast(str, document["actor_id"]),
            calculated_at=cast(str, document["calculated_at"]),
            policy=policy,
            balances=tuple(balances),
            rates=tuple(rates_by_key.values()),
        )
        reproduced = translate_consolidation(request)
    except ConsolidationError:
        raise
    except (ArithmeticError, KeyError, TypeError, ValueError, InvalidAmountError) as exc:
        raise ConsolidationError("Consolidation result payload is invalid.") from exc
    expected = reproduced.to_dict()
    supplied = dict(document)
    if not hmac.compare_digest(
        json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        json.dumps(supplied, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
    ):
        raise ConsolidationError("Consolidation result payload does not reproduce under its declared inputs.")
    return reproduced


def validate_consolidation_run_id(value: object) -> str:
    """Return one bounded deterministic run ID for storage adapters."""

    if not isinstance(value, str) or not _RUN_ID_PATTERN.fullmatch(value):
        raise ConsolidationError("Consolidation run identifier is invalid.")
    return value
