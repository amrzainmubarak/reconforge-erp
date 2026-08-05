"""Deterministic, non-posting bank-statement to ledger control.

The control consumes already parsed statement lines and a local ledger export.
It is deliberately provider-neutral: it does not initiate payments, post a
journal, or authenticate that either source was produced by a bank/ERP.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from reconforge.utils.money import Money

BANK_STATEMENT_CONTROL_SCHEMA_VERSION = 1
BANK_STATEMENT_CONTROL_ALGORITHM_VERSION = "bank-statement-control-v1"
BankStatementStatus = Literal["matched", "exception", "unmatched_bank", "unmatched_ledger", "ambiguous"]
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")


class BankStatementControlError(ValueError):
    """Raised when the closed bank-statement control contract is violated."""


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise BankStatementControlError(f"{field} is invalid.")
    return value.strip()


def _iso_date(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise BankStatementControlError(f"{field} must be an ISO-8601 date.")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise BankStatementControlError(f"{field} must be an ISO-8601 date.") from exc


def _money_dict(value: Money | None) -> dict[str, object] | None:
    return value.to_canonical_dict() if value is not None else None


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


def normalize_bank_reference(value: object) -> str:
    """Normalize a payment reference without inventing a reference for blank input."""

    if not isinstance(value, str):
        raise BankStatementControlError("bank reference must be text.")
    normalized = re.sub(r"[^A-Z0-9]", "", value.upper())
    if not normalized:
        raise BankStatementControlError("bank reference cannot be empty.")
    return normalized[:160]


@dataclass(frozen=True)
class BankStatementRecord:
    line_id: str
    account_id: str
    booking_date: str
    amount: Money
    reference: str
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_id", _identifier(self.line_id, "bank line ID"))
        object.__setattr__(self, "account_id", _identifier(self.account_id, "bank account ID"))
        object.__setattr__(self, "booking_date", _iso_date(self.booking_date, "bank booking date"))
        if not isinstance(self.amount, Money) or not self.amount.amount.is_finite():
            raise BankStatementControlError("bank line amount must be finite Money.")
        object.__setattr__(self, "reference", normalize_bank_reference(self.reference))
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "bank source reference"))


@dataclass(frozen=True)
class BankLedgerRecord:
    record_id: str
    account_id: str
    booking_date: str
    amount: Money
    reference: str
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _identifier(self.record_id, "ledger record ID"))
        object.__setattr__(self, "account_id", _identifier(self.account_id, "ledger account ID"))
        object.__setattr__(self, "booking_date", _iso_date(self.booking_date, "ledger booking date"))
        if not isinstance(self.amount, Money) or not self.amount.amount.is_finite():
            raise BankStatementControlError("ledger amount must be finite Money.")
        object.__setattr__(self, "reference", normalize_bank_reference(self.reference))
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "ledger source reference"))


@dataclass(frozen=True)
class BankStatementDecision:
    bank_line_id: str
    account_id: str
    status: BankStatementStatus
    ledger_record_ids: tuple[str, ...]
    amount_variance: Money | None
    days_variance: int | None
    reason_code: str

    def to_dict(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "amount_variance": _money_dict(self.amount_variance),
            "bank_line_id": self.bank_line_id,
            "days_variance": self.days_variance,
            "ledger_record_ids": list(self.ledger_record_ids),
            "reason_code": self.reason_code,
            "status": self.status,
        }


@dataclass(frozen=True)
class BankStatementControlRun:
    schema_version: int
    algorithm_version: str
    amount_tolerance: Money
    date_window_days: int
    input_digests: tuple[str, ...]
    decisions: tuple[BankStatementDecision, ...]
    decision_digest: str

    @property
    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for decision in self.decisions:
            counts[decision.status] = counts.get(decision.status, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "amount_tolerance": self.amount_tolerance.to_canonical_dict(),
            "date_window_days": self.date_window_days,
            "decision_digest": self.decision_digest,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "input_digests": list(self.input_digests),
            "schema_version": self.schema_version,
            "status_counts": self.status_counts,
        }


def run_bank_statement_control(
    bank_lines: tuple[BankStatementRecord, ...],
    ledger_records: tuple[BankLedgerRecord, ...],
    *,
    amount_tolerance: Money,
    date_window_days: int = 1,
    input_digests: tuple[str, ...] = (),
) -> BankStatementControlRun:
    """Match bank lines to ledger records by normalized reference and exact bounds."""

    if not isinstance(amount_tolerance, Money) or amount_tolerance.amount < 0:
        raise BankStatementControlError("amount tolerance must be non-negative Money.")
    if isinstance(date_window_days, bool) or not isinstance(date_window_days, int) or not 0 <= date_window_days <= 366:
        raise BankStatementControlError("date window must be an integer from 0 to 366 days.")
    if not bank_lines and not ledger_records:
        raise BankStatementControlError("bank statement control requires at least one record.")
    bank_ids = [item.line_id for item in bank_lines]
    ledger_ids = [item.record_id for item in ledger_records]
    if len(bank_ids) != len(set(bank_ids)):
        raise BankStatementControlError("bank line IDs must be unique.")
    if len(ledger_ids) != len(set(ledger_ids)):
        raise BankStatementControlError("ledger record IDs must be unique.")
    all_currencies = [item.amount.currency for item in bank_lines] + [item.amount.currency for item in ledger_records]
    if any(currency != amount_tolerance.currency for currency in all_currencies):
        raise BankStatementControlError("all records and tolerance must use one currency.")
    by_reference: dict[str, list[BankLedgerRecord]] = {}
    for record in ledger_records:
        by_reference.setdefault(record.reference, []).append(record)
    used_ledger_ids: set[str] = set()
    decisions: list[BankStatementDecision] = []
    for bank in sorted(bank_lines, key=lambda item: (item.account_id, item.booking_date, item.line_id)):
        candidates = sorted(by_reference.get(bank.reference, []), key=lambda item: item.record_id)
        if not candidates:
            decisions.append(BankStatementDecision(bank.line_id, bank.account_id, "unmatched_bank", (), None, None, "BANK_LINE_HAS_NO_LEDGER_CANDIDATE"))
            continue
        available = [candidate for candidate in candidates if candidate.record_id not in used_ledger_ids]
        if len(available) != 1:
            decisions.append(
                BankStatementDecision(
                    bank.line_id,
                    bank.account_id,
                    "ambiguous",
                    tuple(candidate.record_id for candidate in candidates),
                    None,
                    None,
                    "MULTIPLE_LEDGER_CANDIDATES_FOR_BANK_LINE" if len(available) > 1 else "LEDGER_CANDIDATES_ALREADY_USED",
                )
            )
            continue
        ledger = available[0]
        amount_variance = ledger.amount - bank.amount
        days_variance = abs((date.fromisoformat(ledger.booking_date) - date.fromisoformat(bank.booking_date)).days)
        if ledger.account_id != bank.account_id:
            decisions.append(BankStatementDecision(bank.line_id, bank.account_id, "exception", (ledger.record_id,), amount_variance, days_variance, "BANK_LEDGER_ACCOUNT_MISMATCH"))
            continue
        if abs(amount_variance.amount) > amount_tolerance.amount:
            decisions.append(BankStatementDecision(bank.line_id, bank.account_id, "exception", (ledger.record_id,), amount_variance, days_variance, "BANK_LEDGER_AMOUNT_VARIANCE"))
            continue
        if days_variance > date_window_days:
            decisions.append(BankStatementDecision(bank.line_id, bank.account_id, "exception", (ledger.record_id,), amount_variance, days_variance, "BANK_LEDGER_DATE_OUTSIDE_WINDOW"))
            continue
        used_ledger_ids.add(ledger.record_id)
        decisions.append(BankStatementDecision(bank.line_id, bank.account_id, "matched", (ledger.record_id,), amount_variance, days_variance, "BANK_LEDGER_RECONCILED"))
    for record in sorted(ledger_records, key=lambda item: (item.account_id, item.booking_date, item.record_id)):
        if record.record_id not in used_ledger_ids and not any(record.record_id in item.ledger_record_ids for item in decisions):
            decisions.append(BankStatementDecision(record.record_id, record.account_id, "unmatched_ledger", (record.record_id,), None, None, "LEDGER_RECORD_HAS_NO_BANK_LINE"))
    ordered = tuple(sorted(decisions, key=lambda item: (item.account_id, item.bank_line_id, item.status, item.ledger_record_ids)))
    payload = {
        "algorithm_version": BANK_STATEMENT_CONTROL_ALGORITHM_VERSION,
        "amount_tolerance": amount_tolerance.to_canonical_dict(),
        "date_window_days": date_window_days,
        "decisions": [item.to_dict() for item in ordered],
        "input_digests": sorted(set(input_digests)),
        "schema_version": BANK_STATEMENT_CONTROL_SCHEMA_VERSION,
    }
    return BankStatementControlRun(
        BANK_STATEMENT_CONTROL_SCHEMA_VERSION,
        BANK_STATEMENT_CONTROL_ALGORITHM_VERSION,
        amount_tolerance,
        date_window_days,
        tuple(sorted(set(input_digests))),
        ordered,
        _digest(payload),
    )


__all__ = [
    "BANK_STATEMENT_CONTROL_ALGORITHM_VERSION",
    "BANK_STATEMENT_CONTROL_SCHEMA_VERSION",
    "BankLedgerRecord",
    "BankStatementControlError",
    "BankStatementControlRun",
    "BankStatementDecision",
    "BankStatementRecord",
    "normalize_bank_reference",
    "run_bank_statement_control",
]
