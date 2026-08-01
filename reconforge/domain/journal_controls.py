"""Pure deterministic journal-control policy evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from reconforge.utils.money import InvalidAmountError, parse_amount


class JournalPolicyError(ValueError):
    """Raised when journal policy input cannot be evaluated safely."""


def journal_threshold(value: object) -> Decimal:
    """Return a finite non-negative exact threshold."""

    try:
        parsed = parse_amount(value)
    except InvalidAmountError as exc:
        raise JournalPolicyError("High-value journal threshold is invalid.") from exc
    if parsed < 0:
        raise JournalPolicyError("High-value journal threshold cannot be negative.")
    return parsed


def evaluate_journal_policies(
    row: Mapping[str, Any] | Any,
    *,
    period_end: str,
    high_value_threshold: Decimal,
    high_risk_accounts: set[str],
) -> list[tuple[str, str, str]]:
    """Evaluate one normalized journal row without persistence or ambient state."""

    policies: list[tuple[str, str, str]] = []
    posting_date = _date(_value(row, "posting_date"))
    period_end_date = _date(period_end)
    if bool(_value(row, "is_manual")):
        policies.append(("MANUAL_JOURNAL", "medium", "Manual journal entry requires documented review."))
    if period_end_date is not None and posting_date is not None and posting_date > period_end_date:
        policies.append(("POST_PERIOD", "high", "Journal posting date is after the configured period end."))
    if posting_date is not None and posting_date.weekday() >= 5:
        policies.append(("WEEKEND_POSTING", "medium", "Journal was posted on a weekend date."))
    if not _text(_value(row, "reference")):
        policies.append(("MISSING_REFERENCE", "medium", "Journal is missing a source reference."))
    if not _text(_value(row, "approver")):
        policies.append(("MISSING_APPROVER", "high", "Journal is missing approver evidence/reference."))
    try:
        amount = parse_amount(_value(row, "amount_decimal"))
    except InvalidAmountError as exc:
        raise JournalPolicyError("Stored journal amount is invalid.") from exc
    if abs(amount) >= high_value_threshold:
        policies.append(("HIGH_VALUE", "high", "Journal amount exceeds the configured high-value threshold."))
    if str(_value(row, "account_code")) in high_risk_accounts:
        policies.append(("HIGH_RISK_ACCOUNT", "high", "Journal uses a configured high-risk account."))
    return policies


def _value(row: Mapping[str, Any] | Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError) as exc:
        raise JournalPolicyError(f"Journal policy row is missing {key}.") from exc


def _text(value: object) -> str:
    return str(value or "").strip()


def _date(value: object) -> date | None:
    text = _text(value)
    if not text:
        return None
    for candidate in (text, text[:10]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None
